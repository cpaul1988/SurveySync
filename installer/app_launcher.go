//go:build windows

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const appVersion = "9.3.2"
const productName = "SurveySync"

const (
	errorAlreadyExists                     = 183
	createNoWindow                         = 0x08000000
	detachedProcess                        = 0x00000008
	createNewProcessGroup                  = 0x00000200
	processSetQuota                        = 0x0100
	processTerminate                       = 0x0001
	jobObjectExtendedLimitInformationClass = 9
	jobObjectLimitKillOnJobClose           = 0x00002000
)

type jobObjectBasicLimitInformation struct {
	PerProcessUserTimeLimit int64
	PerJobUserTimeLimit     int64
	LimitFlags              uint32
	MinimumWorkingSetSize   uintptr
	MaximumWorkingSetSize   uintptr
	ActiveProcessLimit      uint32
	Affinity                uintptr
	PriorityClass           uint32
	SchedulingClass         uint32
}

type ioCounters struct {
	ReadOperationCount  uint64
	WriteOperationCount uint64
	OtherOperationCount uint64
	ReadTransferCount   uint64
	WriteTransferCount  uint64
	OtherTransferCount  uint64
}

type jobObjectExtendedLimitInformation struct {
	BasicLimitInformation jobObjectBasicLimitInformation
	IoInfo                ioCounters
	ProcessMemoryLimit    uintptr
	JobMemoryLimit        uintptr
	PeakProcessMemoryUsed uintptr
	PeakJobMemoryUsed     uintptr
}

var (
	kernel32                 = syscall.NewLazyDLL("kernel32.dll")
	user32                   = syscall.NewLazyDLL("user32.dll")
	procCreateMutexW         = kernel32.NewProc("CreateMutexW")
	procGetLastError         = kernel32.NewProc("GetLastError")
	procCloseHandle          = kernel32.NewProc("CloseHandle")
	procCreateJobObjectW     = kernel32.NewProc("CreateJobObjectW")
	procSetInformationJobObj = kernel32.NewProc("SetInformationJobObject")
	procAssignProcessToJob   = kernel32.NewProc("AssignProcessToJobObject")
	procOpenProcess          = kernel32.NewProc("OpenProcess")
	procMessageBoxW          = user32.NewProc("MessageBoxW")
)

func messageBox(title, text string, flags uintptr) {
	t, _ := syscall.UTF16PtrFromString(title)
	m, _ := syscall.UTF16PtrFromString(text)
	_, _, _ = procMessageBoxW.Call(0, uintptr(unsafe.Pointer(m)), uintptr(unsafe.Pointer(t)), flags)
}

func dataLogPath() string {
	base := strings.TrimSpace(os.Getenv("LOCALAPPDATA"))
	if base == "" {
		base = os.TempDir()
	}
	dir := filepath.Join(base, "SurveySync", "logs")
	_ = os.MkdirAll(dir, 0755)
	return filepath.Join(dir, "launcher.log")
}

func appendLog(path, msg string) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = fmt.Fprintf(f, "%s | %s\r\n", time.Now().Format("2006-01-02 15:04:05.000"), msg)
}

type pendingUpdate struct {
	Version       string `json:"version"`
	InstallerPath string `json:"installer_path"`
	Sha256        string `json:"sha256"`
	SizeBytes     int64  `json:"size_bytes"`
}

func updateDataRoot() string {
	base := strings.TrimSpace(os.Getenv("LOCALAPPDATA"))
	if base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "SurveySync")
}

func parseVersion(version string) ([]int, error) {
	parts := strings.Split(strings.TrimSpace(version), ".")
	if len(parts) == 0 {
		return nil, fmt.Errorf("version is empty")
	}
	out := make([]int, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			return nil, fmt.Errorf("version contains an empty component")
		}
		n, err := strconv.Atoi(part)
		if err != nil || n < 0 {
			return nil, fmt.Errorf("invalid version component %q", part)
		}
		out = append(out, n)
	}
	return out, nil
}

func compareVersions(a, b string) (int, error) {
	av, err := parseVersion(a)
	if err != nil {
		return 0, err
	}
	bv, err := parseVersion(b)
	if err != nil {
		return 0, err
	}
	maxLen := len(av)
	if len(bv) > maxLen {
		maxLen = len(bv)
	}
	for i := 0; i < maxLen; i++ {
		ai, bi := 0, 0
		if i < len(av) {
			ai = av[i]
		}
		if i < len(bv) {
			bi = bv[i]
		}
		if ai < bi {
			return -1, nil
		}
		if ai > bi {
			return 1, nil
		}
	}
	return 0, nil
}

func readPendingUpdate(pendingPath string) (pendingUpdate, error) {
	var pending pendingUpdate
	raw, err := os.ReadFile(pendingPath)
	if err != nil {
		return pending, err
	}
	if err := json.Unmarshal(raw, &pending); err != nil {
		return pending, fmt.Errorf("parse pending update handoff: %w", err)
	}
	return pending, nil
}

func discardStalePendingUpdate(logFile string) {
	pendingPath := filepath.Join(updateDataRoot(), "pending_update.json")
	pending, err := readPendingUpdate(pendingPath)
	if os.IsNotExist(err) {
		return
	}
	if err != nil {
		appendLog(logFile, "WARNING | Could not inspect pending update during startup: "+err.Error())
		return
	}
	cmp, err := compareVersions(strings.TrimSpace(pending.Version), appVersion)
	if err != nil {
		appendLog(logFile, "WARNING | Pending update has an invalid version and was left untouched: "+err.Error())
		return
	}
	if cmp <= 0 {
		if err := os.Remove(pendingPath); err != nil && !os.IsNotExist(err) {
			appendLog(logFile, fmt.Sprintf("WARNING | Could not remove stale pending update v%s: %v", pending.Version, err))
			return
		}
		appendLog(logFile, fmt.Sprintf("Discarded stale pending update v%s because installed launcher is v%s", pending.Version, appVersion))
	}
}

type helperStatus struct {
	State     string `json:"state"`
	HelperPID int    `json:"helper_pid"`
	Version   string `json:"version"`
}

func waitForHelperHeartbeat(statusPath string, helperPID int, timeout time.Duration) (helperStatus, error) {
	deadline := time.Now().Add(timeout)
	var lastErr error
	for time.Now().Before(deadline) {
		raw, err := os.ReadFile(statusPath)
		if err == nil {
			var status helperStatus
			if json.Unmarshal(raw, &status) == nil && status.HelperPID == helperPID {
				state := strings.TrimSpace(status.State)
				if state != "" && state != "started" {
					return status, nil
				}
			}
			lastErr = fmt.Errorf("status file did not match helper PID %d", helperPID)
		} else if !os.IsNotExist(err) {
			lastErr = err
		}
		time.Sleep(50 * time.Millisecond)
	}
	if lastErr != nil {
		return helperStatus{}, fmt.Errorf("native updater helper did not report ready state within %s: %w", timeout, lastErr)
	}
	return helperStatus{}, fmt.Errorf("native updater helper did not report ready state within %s", timeout)
}

func verifyPendingInstaller(pending pendingUpdate) (string, string, int64, error) {
	installer := strings.TrimSpace(pending.InstallerPath)
	if installer == "" || !strings.EqualFold(filepath.Ext(installer), ".exe") {
		return "", "", 0, fmt.Errorf("pending update installer path is invalid")
	}
	absInstaller, err := filepath.Abs(installer)
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve pending installer path: %w", err)
	}
	updatesRoot, err := filepath.Abs(filepath.Join(updateDataRoot(), "updates"))
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve update directory: %w", err)
	}
	rootPrefix := strings.ToLower(updatesRoot + string(os.PathSeparator))
	if !strings.HasPrefix(strings.ToLower(absInstaller), rootPrefix) {
		return "", "", 0, fmt.Errorf("pending installer is outside the SurveySync updates folder")
	}
	info, err := os.Stat(absInstaller)
	if err != nil {
		return "", "", 0, fmt.Errorf("pending installer is unavailable: %w", err)
	}
	if pending.SizeBytes <= 0 || info.Size() != pending.SizeBytes {
		return "", "", 0, fmt.Errorf("pending installer size changed after verification")
	}
	expectedHash := strings.ToLower(strings.TrimSpace(pending.Sha256))
	if len(expectedHash) != 64 {
		return "", "", 0, fmt.Errorf("pending installer checksum is invalid")
	}
	installerBytes, err := os.ReadFile(absInstaller)
	if err != nil {
		return "", "", 0, fmt.Errorf("re-read pending installer for verification: %w", err)
	}
	if len(installerBytes) < 2 || string(installerBytes[:2]) != "MZ" {
		return "", "", 0, fmt.Errorf("pending installer is no longer a Windows executable")
	}
	sum := sha256.Sum256(installerBytes)
	actualHash := hex.EncodeToString(sum[:])
	if !strings.EqualFold(actualHash, expectedHash) {
		return "", "", 0, fmt.Errorf("pending installer SHA-256 changed after verification")
	}
	return absInstaller, actualHash, info.Size(), nil
}

func launchPendingUpdate(logFile string) (bool, error) {
	pendingPath := filepath.Join(updateDataRoot(), "pending_update.json")
	pending, err := readPendingUpdate(pendingPath)
	if os.IsNotExist(err) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read pending update handoff: %w", err)
	}
	cmp, err := compareVersions(strings.TrimSpace(pending.Version), appVersion)
	if err != nil {
		return false, fmt.Errorf("pending update version is invalid: %w", err)
	}
	if cmp <= 0 {
		if err := os.Remove(pendingPath); err != nil && !os.IsNotExist(err) {
			return false, fmt.Errorf("remove stale pending update v%s: %w", pending.Version, err)
		}
		appendLog(logFile, fmt.Sprintf("Discarded stale pending update v%s because installed launcher is v%s", pending.Version, appVersion))
		return false, nil
	}

	absInstaller, actualHash, installerSize, err := verifyPendingInstaller(pending)
	if err != nil {
		return false, err
	}
	appendLog(logFile, fmt.Sprintf("Re-verified pending update v%s SHA-256=%s size=%d", pending.Version, actualHash, installerSize))

	exePath, err := os.Executable()
	if err != nil {
		return false, fmt.Errorf("resolve installed launcher path for updater helper: %w", err)
	}
	helperExe := filepath.Join(filepath.Dir(exePath), "SurveySyncUpdater.exe")
	if _, err := os.Stat(helperExe); err != nil {
		return false, fmt.Errorf("native updater helper is missing: %s", helperExe)
	}
	helperLog := filepath.Join(updateDataRoot(), "logs", "update_helper.log")
	statusPath := filepath.Join(updateDataRoot(), "updates", "update_helper_status.json")
	_ = os.Remove(statusPath)

	args := []string{
		"--launcher-pid", fmt.Sprintf("%d", os.Getpid()),
		"--pending-file", pendingPath,
		"--status-file", statusPath,
		"--log-file", helperLog,
	}
	helperCmd := exec.Command(helperExe, args...)
	helperCmd.Dir = filepath.Dir(helperExe)
	helperCmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: detachedProcess | createNewProcessGroup,
	}
	if err := helperCmd.Start(); err != nil {
		return false, fmt.Errorf("start native updater helper: %w", err)
	}
	helperPID := helperCmd.Process.Pid
	appendLog(logFile, fmt.Sprintf("Native updater helper process created PID=%d for pending v%s", helperPID, pending.Version))

	status, err := waitForHelperHeartbeat(statusPath, helperPID, 2500*time.Millisecond)
	if err != nil {
		_ = helperCmd.Process.Kill()
		return false, err
	}
	if status.State == "error" {
		return false, fmt.Errorf("native updater helper reported an initialization error; see %s", helperLog)
	}
	appendLog(logFile, fmt.Sprintf("Pending update v%s handed off to native helper PID=%d state=%s installer=%s", pending.Version, helperPID, status.State, absInstaller))
	return true, nil
}
func acquireSingleInstanceMutex(logFile string) (uintptr, bool) {
	name, _ := syscall.UTF16PtrFromString("Local\\CleverBirdDevelopment.SurveySync")
	h, _, _ := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if h == 0 {
		appendLog(logFile, "WARNING | Could not create the single-instance mutex; continuing")
		return 0, true
	}
	lastErr, _, _ := procGetLastError.Call()
	if lastErr == errorAlreadyExists {
		_, _, _ = procCloseHandle.Call(h)
		return 0, false
	}
	return h, true
}

func createKillOnCloseJob(logFile string) uintptr {
	h, _, _ := procCreateJobObjectW.Call(0, 0)
	if h == 0 {
		appendLog(logFile, "WARNING | Could not create Windows Job Object")
		return 0
	}
	info := jobObjectExtendedLimitInformation{}
	info.BasicLimitInformation.LimitFlags = jobObjectLimitKillOnJobClose
	r, _, _ := procSetInformationJobObj.Call(
		h,
		jobObjectExtendedLimitInformationClass,
		uintptr(unsafe.Pointer(&info)),
		unsafe.Sizeof(info),
	)
	if r == 0 {
		appendLog(logFile, "WARNING | Could not configure kill-on-close Job Object")
		_, _, _ = procCloseHandle.Call(h)
		return 0
	}
	return h
}

func assignPidToJob(job uintptr, pid int, logFile string) {
	if job == 0 || pid <= 0 {
		return
	}
	ph, _, _ := procOpenProcess.Call(processSetQuota|processTerminate, 0, uintptr(pid))
	if ph == 0 {
		appendLog(logFile, fmt.Sprintf("WARNING | Could not open child PID %d for Job Object assignment", pid))
		return
	}
	defer procCloseHandle.Call(ph)
	r, _, _ := procAssignProcessToJob.Call(job, ph)
	if r == 0 {
		appendLog(logFile, fmt.Sprintf("WARNING | Could not assign child PID %d to Job Object", pid))
	}
}

func main() {
	logFile := dataLogPath()
	appendLog(logFile, "============================================================")
	appendLog(logFile, productName+" "+appVersion+" native launcher started")
	discardStalePendingUpdate(logFile)

	mutex, ok := acquireSingleInstanceMutex(logFile)
	if !ok {
		messageBox(productName, "SurveySync is already running.\r\n\r\nIf no window is visible, wait a few seconds and try again. If it remains unavailable, use Windows Task Manager to close the old SurveySync process.", 0x00000040)
		return
	}
	if mutex != 0 {
		defer procCloseHandle.Call(mutex)
	}

	exePath, err := os.Executable()
	if err != nil {
		messageBox(productName, "SurveySync could not determine its installation folder.\r\n\r\nSee launcher.log for details.", 0x00000010)
		appendLog(logFile, "ERROR | os.Executable: "+err.Error())
		return
	}
	root := filepath.Dir(exePath)
	python := filepath.Join(root, ".venv", "Scripts", "python.exe")
	desktopPy := filepath.Join(root, "desktop.py")
	if _, err := os.Stat(python); err != nil {
		appendLog(logFile, "ERROR | Missing private Python runtime: "+python)
		messageBox(productName, "SurveySync's private runtime is missing or incomplete.\r\n\r\nRun the latest SurveySync Setup again to repair the installation.\r\n\r\nLog: "+logFile, 0x00000010)
		return
	}
	if _, err := os.Stat(desktopPy); err != nil {
		appendLog(logFile, "ERROR | Missing desktop.py: "+desktopPy)
		messageBox(productName, "SurveySync application files are incomplete.\r\n\r\nRun the latest Setup again to repair the installation.\r\n\r\nLog: "+logFile, 0x00000010)
		return
	}

	logHandle, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		messageBox(productName, "SurveySync could not open its launcher log.\r\n\r\n"+err.Error(), 0x00000010)
		return
	}
	defer logHandle.Close()

	args := []string{desktopPy}
	args = append(args, os.Args[1:]...)
	cmd := exec.Command(python, args...)
	cmd.Dir = root
	cmd.Stdout = logHandle
	cmd.Stderr = logHandle
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}

	appendLog(logFile, "Launching private Python application runtime")
	if err := cmd.Start(); err != nil {
		appendLog(logFile, "ERROR | Could not start application runtime: "+err.Error())
		messageBox(productName, "SurveySync could not start.\r\n\r\n"+err.Error()+"\r\n\r\nLog: "+logFile, 0x00000010)
		return
	}

	job := createKillOnCloseJob(logFile)
	if job != 0 {
		defer procCloseHandle.Call(job)
		assignPidToJob(job, cmd.Process.Pid, logFile)
	}
	appendLog(logFile, fmt.Sprintf("Application child PID=%d", cmd.Process.Pid))

	err = cmd.Wait()
	if launched, updateErr := launchPendingUpdate(logFile); updateErr != nil {
		appendLog(logFile, "ERROR | Update handoff failed: "+updateErr.Error())
		messageBox(productName+" Update", "The update was downloaded, but Setup could not be started automatically.\r\n\r\n"+updateErr.Error()+"\r\n\r\nSee launcher.log for details.", 0x00000010)
		return
	} else if launched {
		appendLog(logFile, "Application closed for update; detached Setup handoff created")
		return
	}
	if err == nil {
		appendLog(logFile, "Application exited normally")
		return
	}
	appendLog(logFile, "ERROR | Application runtime exited unexpectedly: "+err.Error())
	messageBox(productName, "SurveySync closed unexpectedly.\r\n\r\nA diagnostic launcher log was saved at:\r\n"+logFile, 0x00000010)
}

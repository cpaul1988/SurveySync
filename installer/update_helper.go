//go:build windows

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const updaterName = "SurveySync Updater"

const (
	updaterErrorAlreadyExists = 183
	synchronizeAccess         = 0x00100000
	waitObject0               = 0x00000000
	waitTimeout               = 0x00000102
	waitFailed                = 0xFFFFFFFF
	updaterNewProcessGroup    = 0x00000200
)

var (
	updaterKernel32         = syscall.NewLazyDLL("kernel32.dll")
	updaterCreateMutexW     = updaterKernel32.NewProc("CreateMutexW")
	updaterGetLastError     = updaterKernel32.NewProc("GetLastError")
	updaterCloseHandle      = updaterKernel32.NewProc("CloseHandle")
	updaterOpenProcess      = updaterKernel32.NewProc("OpenProcess")
	updaterWaitForSingleObj = updaterKernel32.NewProc("WaitForSingleObject")
)

type updateHandoff struct {
	Version       string `json:"version"`
	ReleaseID     string `json:"release_id"`
	InstallerPath string `json:"installer_path"`
	Sha256        string `json:"sha256"`
	SizeBytes     int64  `json:"size_bytes"`
}

type updaterStatus struct {
	State        string `json:"state"`
	HelperPID    int    `json:"helper_pid"`
	LauncherPID  int    `json:"launcher_pid"`
	Version      string `json:"version,omitempty"`
	InstallerPID int    `json:"installer_pid,omitempty"`
	Message      string `json:"message,omitempty"`
	UpdatedAt    string `json:"updated_at"`
}

func updaterDataRoot() string {
	if override := strings.TrimSpace(os.Getenv("SURVEYSYNC_CONFIG_ROOT")); override != "" {
		if absolute, err := filepath.Abs(override); err == nil {
			return absolute
		}
	}
	base := strings.TrimSpace(os.Getenv("LOCALAPPDATA"))
	if base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "SurveySync")
}

func updaterAppendLog(path, msg string) {
	if strings.TrimSpace(path) == "" {
		return
	}
	_ = os.MkdirAll(filepath.Dir(path), 0755)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = fmt.Fprintf(f, "%s | %s\r\n", time.Now().Format("2006-01-02 15:04:05.000"), msg)
}

func writeUpdaterStatus(path string, status updaterStatus) {
	if strings.TrimSpace(path) == "" {
		return
	}
	status.UpdatedAt = time.Now().UTC().Format(time.RFC3339Nano)
	raw, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return
	}
	_ = os.MkdirAll(filepath.Dir(path), 0755)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0644); err != nil {
		return
	}
	_ = os.Remove(path)
	if err := os.Rename(tmp, path); err != nil {
		_ = os.WriteFile(path, raw, 0644)
		_ = os.Remove(tmp)
	}
}

func acquireUpdaterMutex() (uintptr, bool) {
	name, _ := syscall.UTF16PtrFromString("Local\\CleverBirdDevelopment.SurveySyncUpdater")
	h, _, lastErr := updaterCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(name)))
	if h == 0 {
		return 0, false
	}
	if lastErr == syscall.Errno(updaterErrorAlreadyExists) {
		_, _, _ = updaterCloseHandle.Call(h)
		return 0, false
	}
	return h, true
}

func readUpdateHandoff(path string) (updateHandoff, error) {
	var pending updateHandoff
	raw, err := os.ReadFile(path)
	if err != nil {
		return pending, err
	}
	if err := json.Unmarshal(raw, &pending); err != nil {
		return pending, fmt.Errorf("parse pending update handoff: %w", err)
	}
	return pending, nil
}

func verifyUpdateInstaller(pending updateHandoff) (string, string, int64, error) {
	installer := strings.TrimSpace(pending.InstallerPath)
	if installer == "" || !strings.EqualFold(filepath.Ext(installer), ".exe") {
		return "", "", 0, fmt.Errorf("pending installer path is invalid")
	}
	absInstaller, err := filepath.Abs(installer)
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve installer path: %w", err)
	}
	updatesRoot, err := filepath.Abs(filepath.Join(updaterDataRoot(), "updates"))
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve updates folder: %w", err)
	}
	updatesRoot, err = filepath.EvalSymlinks(updatesRoot)
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve updates folder links: %w", err)
	}
	absInstaller, err = filepath.EvalSymlinks(absInstaller)
	if err != nil {
		return "", "", 0, fmt.Errorf("resolve installer links: %w", err)
	}
	prefix := strings.ToLower(updatesRoot + string(os.PathSeparator))
	if !strings.HasPrefix(strings.ToLower(absInstaller), prefix) {
		return "", "", 0, fmt.Errorf("installer is outside the SurveySync updates folder")
	}
	info, err := os.Stat(absInstaller)
	if err != nil {
		return "", "", 0, fmt.Errorf("installer is unavailable: %w", err)
	}
	if pending.SizeBytes <= 0 || info.Size() != pending.SizeBytes {
		return "", "", 0, fmt.Errorf("installer size no longer matches the verified handoff")
	}
	expectedHash := strings.ToLower(strings.TrimSpace(pending.Sha256))
	if len(expectedHash) != 64 {
		return "", "", 0, fmt.Errorf("installer checksum in handoff is invalid")
	}
	installerBytes, err := os.ReadFile(absInstaller)
	if err != nil {
		return "", "", 0, fmt.Errorf("read installer for verification: %w", err)
	}
	if len(installerBytes) < 2 || string(installerBytes[:2]) != "MZ" {
		return "", "", 0, fmt.Errorf("installer no longer has a Windows executable header")
	}
	sum := sha256.Sum256(installerBytes)
	actualHash := hex.EncodeToString(sum[:])
	if !strings.EqualFold(actualHash, expectedHash) {
		return "", "", 0, fmt.Errorf("installer SHA-256 no longer matches the verified handoff")
	}
	return absInstaller, actualHash, info.Size(), nil
}

func waitForLauncherExit(pid int, timeout time.Duration) error {
	if pid <= 0 {
		return fmt.Errorf("launcher PID is invalid")
	}
	h, _, openErr := updaterOpenProcess.Call(synchronizeAccess, 0, uintptr(pid))
	if h == 0 {
		// ERROR_INVALID_PARAMETER means this PID no longer exists. Access denied
		// or another error is not proof of exit and must not start installation.
		if openErr == syscall.Errno(87) {
			return nil
		}
		return fmt.Errorf("cannot verify launcher exit: %v", openErr)
	}
	defer updaterCloseHandle.Call(h)
	result, _, _ := updaterWaitForSingleObj.Call(h, uintptr(timeout.Milliseconds()))
	switch result {
	case waitObject0:
		return nil
	case waitTimeout:
		return fmt.Errorf("launcher PID %d did not exit within %s", pid, timeout)
	case waitFailed:
		lastErr, _, _ := updaterGetLastError.Call()
		return fmt.Errorf("WaitForSingleObject failed for launcher PID %d (Windows error %d)", pid, lastErr)
	default:
		return fmt.Errorf("unexpected wait result 0x%x for launcher PID %d", result, pid)
	}
}

func main() {
	defaultRoot := updaterDataRoot()
	launcherPID := flag.Int("launcher-pid", 0, "SurveySync.exe launcher PID to wait for")
	pendingFile := flag.String("pending-file", filepath.Join(defaultRoot, "pending_update.json"), "verified pending update handoff")
	statusFile := flag.String("status-file", filepath.Join(defaultRoot, "updates", "update_helper_status.json"), "helper status JSON")
	logFile := flag.String("log-file", filepath.Join(defaultRoot, "logs", "update_helper.log"), "helper diagnostic log")
	installDir := flag.String("install-dir", "", "existing SurveySync installation")
	flag.Parse()

	status := updaterStatus{State: "started", HelperPID: os.Getpid(), LauncherPID: *launcherPID}
	updaterAppendLog(*logFile, "============================================================")
	updaterAppendLog(*logFile, fmt.Sprintf("%s started PID=%d launcherPID=%d", updaterName, os.Getpid(), *launcherPID))
	writeUpdaterStatus(*statusFile, status)

	mutex, ok := acquireUpdaterMutex()
	if !ok {
		status.State = "already_running"
		status.Message = "Another SurveySync updater helper is already active."
		writeUpdaterStatus(*statusFile, status)
		updaterAppendLog(*logFile, status.Message)
		return
	}
	if mutex != 0 {
		defer updaterCloseHandle.Call(mutex)
	}

	pending, err := readUpdateHandoff(*pendingFile)
	if err != nil {
		status.State = "error"
		status.Message = "Could not read pending update: " + err.Error()
		writeUpdaterStatus(*statusFile, status)
		updaterAppendLog(*logFile, "ERROR | "+status.Message)
		return
	}
	status.Version = strings.TrimSpace(pending.Version)
	status.State = "waiting_for_launcher"
	status.Message = fmt.Sprintf("Waiting for SurveySync.exe launcher PID %d to exit.", *launcherPID)
	writeUpdaterStatus(*statusFile, status)
	updaterAppendLog(*logFile, status.Message)

	if err := waitForLauncherExit(*launcherPID, 45*time.Second); err != nil {
		status.State = "error"
		status.Message = err.Error()
		writeUpdaterStatus(*statusFile, status)
		updaterAppendLog(*logFile, "ERROR | "+status.Message)
		return
	}
	updaterAppendLog(*logFile, "Launcher exited; re-verifying staged installer")

	installer, actualHash, installerSize, err := verifyUpdateInstaller(pending)
	if err != nil {
		status.State = "error"
		status.Message = err.Error()
		writeUpdaterStatus(*statusFile, status)
		updaterAppendLog(*logFile, "ERROR | "+status.Message)
		return
	}
	status.State = "verified"
	status.Message = fmt.Sprintf("Installer re-verified SHA-256=%s size=%d", actualHash, installerSize)
	writeUpdaterStatus(*statusFile, status)
	updaterAppendLog(*logFile, status.Message)

	// Give Windows a brief moment to release the launcher's executable image before Setup copies files.
	time.Sleep(350 * time.Millisecond)
	destination, err := filepath.Abs(*installDir)
	if *installDir == "" || err != nil {
		status.State = "error"
		status.Message = "Missing or invalid existing installation directory."
		writeUpdaterStatus(*statusFile, status)
		return
	}
	if _, err := os.Stat(filepath.Join(destination, "SurveySync.exe")); err != nil {
		status.State = "error"
		status.Message = "Existing SurveySync launcher is missing."
		writeUpdaterStatus(*statusFile, status)
		return
	}
	setupLog := filepath.Join(updaterDataRoot(), "logs", "update_setup.log")
	cmd := exec.Command(installer, "/DIR="+destination, "/NORESTART", "/LOG="+setupLog)
	cmd.Dir = filepath.Dir(installer)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: updaterNewProcessGroup}
	if err := cmd.Start(); err != nil {
		status.State = "error"
		status.Message = "Could not start Setup: " + err.Error()
		writeUpdaterStatus(*statusFile, status)
		updaterAppendLog(*logFile, "ERROR | "+status.Message)
		return
	}
	setupPID := cmd.Process.Pid
	status.State = "installer_started"
	status.InstallerPID = setupPID
	status.Message = fmt.Sprintf("Setup started successfully PID=%d", setupPID)
	writeUpdaterStatus(*statusFile, status)
	updaterAppendLog(*logFile, status.Message)

	// Starting Setup is not installation success. Retain actionable status for
	// cancellation/failure and do not silently retry a rejected update on Exit.
	err = cmd.Wait()
	if err != nil {
		status.State = "installer_failed"
		status.Message = "Setup did not complete: " + err.Error() + ". See " + setupLog
		_ = os.Rename(*pendingFile, *pendingFile+".failed")
	} else {
		installed, readErr := os.ReadFile(filepath.Join(destination, "VERSION.txt"))
		identity, identityErr := os.ReadFile(filepath.Join(destination, "RELEASE_ID.txt"))
		identityOK := pending.ReleaseID == "" || (identityErr == nil && strings.TrimSpace(string(identity)) == pending.ReleaseID)
		if readErr != nil || strings.TrimSpace(string(installed)) != pending.Version || !identityOK {
			status.State = "installer_failed"
			status.Message = "Setup returned success but the expected version was not found in the target directory."
			_ = os.Rename(*pendingFile, *pendingFile+".failed")
		} else {
			// Record the accepted artifact only after checking the installed build identity.
			id := strings.TrimSpace(string(identity))
			if id == "" {
				id = pending.Version
			}
			receipt, _ := json.Marshal(map[string]interface{}{"version": pending.Version, "release_id": id, "sha256": actualHash})
			receiptPath := filepath.Join(filepath.Dir(*pendingFile), "installed_update.json")
			if writeErr := os.WriteFile(receiptPath, receipt, 0600); writeErr != nil {
				updaterAppendLog(*logFile, "Could not record installed artifact: "+writeErr.Error())
			}
			status.State = "installed"
			status.Message = "Setup completed and installed version was verified."
			_ = os.Remove(*pendingFile)
		}
	}
	writeUpdaterStatus(*statusFile, status)
	updaterAppendLog(*logFile, status.State+" | "+status.Message)

}

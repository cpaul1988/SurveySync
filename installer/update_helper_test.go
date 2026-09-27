//go:build windows

package main

import (
    "crypto/sha256"
    "encoding/hex"
    "os"
    "path/filepath"
    "testing"
    "time"
)

func TestCustomDataRoot(t *testing.T) {
    root := t.TempDir()
    t.Setenv("SURVEYSYNC_CONFIG_ROOT", root)
    if updaterDataRoot() != root { t.Fatal("helper ignored configured data root") }
}

func TestVerifiedInstallerAndMutation(t *testing.T) {
    root := t.TempDir()
    t.Setenv("SURVEYSYNC_CONFIG_ROOT", root)
    folder := filepath.Join(root,"updates")
    if err:=os.MkdirAll(folder,0700);err!=nil{t.Fatal(err)}
    path:=filepath.Join(folder,"test.exe")
    data:=[]byte("MZverified-test-data")
    hash:=sha256.Sum256(data)
    pending:=updateHandoff{Version:"9.4.1",InstallerPath:path,SizeBytes:int64(len(data)),Sha256:hex.EncodeToString(hash[:])}
    if err:=os.WriteFile(path,data,0600);err!=nil{t.Fatal(err)}
    if _,_,_,err:=verifyUpdateInstaller(pending);err!=nil{t.Fatal(err)}
    data[len(data)-1]='!'
    if err:=os.WriteFile(path,data,0600);err!=nil{t.Fatal(err)}
    if _,_,_,err:=verifyUpdateInstaller(pending);err==nil{t.Fatal("mutated bytes accepted")}
    pending.InstallerPath=filepath.Join(root,"outside.exe")
    if err:=os.WriteFile(pending.InstallerPath,data,0600);err!=nil{t.Fatal(err)}
    if _,_,_,err:=verifyUpdateInstaller(pending);err==nil{t.Fatal("outside installer accepted")}
}

func TestInvalidPIDCannotStartSetup(t *testing.T) {
    if err:=waitForLauncherExit(0,time.Millisecond);err==nil{t.Fatal("invalid PID accepted")}
    if err:=waitForLauncherExit(os.Getpid(),time.Millisecond);err==nil{t.Fatal("live process treated as exited")}
}

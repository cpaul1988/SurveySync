//go:build windows

package main

import "testing"

func TestLauncherUsesSameConfiguredDataRoot(t *testing.T) {
    root:=t.TempDir()
    t.Setenv("SURVEYSYNC_CONFIG_ROOT",root)
    if updateDataRoot()!=root{t.Fatal("launcher ignored Python's configured root")}
}
func TestNumericUpdateVersionOrder(t *testing.T) {
    for _,item:=range []struct{a,b string;want int}{{"9.4.1","9.4.0",1},{"9.4.1","9.4.1",0},{"9.4.0","9.4.1",-1},{"9.4","9.4.0",0}} {
        actual,err:=compareVersions(item.a,item.b)
        if err!=nil||actual!=item.want{t.Fatal(item,actual,err)}
    }
}

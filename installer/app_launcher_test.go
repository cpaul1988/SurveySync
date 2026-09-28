//go:build windows

package main

import "testing"

func TestLauncherUsesSameConfiguredDataRoot(t *testing.T) {
	root := t.TempDir()
	t.Setenv("SURVEYSYNC_CONFIG_ROOT", root)
	if updateDataRoot() != root {
		t.Fatal("launcher ignored Python's configured root")
	}
}
func TestNumericUpdateVersionOrder(t *testing.T) {
	for _, item := range []struct {
		a, b string
		want int
	}{{"9.4.1", "9.4.0", 1}, {"9.4.1", "9.4.1", 0}, {"9.4.0", "9.4.1", -1}, {"9.4", "9.4.0", 0}} {
		actual, err := compareVersions(item.a, item.b)
		if err != nil || actual != item.want {
			t.Fatal(item, actual, err)
		}
	}
}

func TestReleaseIdentityOrdering(t *testing.T) {
	cases := []struct {
		a, b string
		want int
	}{
		{"9.4.2-beta.2", "9.4.2-beta.10", -1},
		{"9.4.2-beta.10", "9.4.2-beta.2", 1},
		{"9.4.2", "9.4.2-beta.10", 1},
		{"9.4.2-beta.10+build.a", "9.4.2-beta.10+build.b", 0},
		{"9.4.3-alpha", "9.4.2", 1},
		{"9.4.2-beta.9", "9.4.2-beta.9.1", -1},
		{"9.4.2-beta.9", "9.4.2-beta.a", -1},
		{"9.4.2-beta.9999999999999999999999999", "9.4.2-beta.9999999999999999999999998", 1},
		{"v9.4.2", "9.4.2.0", 0},
	}
	for _, c := range cases {
		got, err := compareReleaseIDs(c.a, c.b)
		if err != nil || got != c.want {
			t.Errorf("%s vs %s = %d %v", c.a, c.b, got, err)
		}
	}
}

func TestReleaseIdentityRejectsInvalid(t *testing.T) {
	for _, bad := range []string{"9.4.2-beta.02", "9.4.2-", "9.4.2+", "9.65536.2", "9.4.2-beta..1", "garbage"} {
		if _, err := compareReleaseIDs(bad, "9.4.1"); err == nil {
			t.Errorf("Accepted malformed release %s", bad)
		}
	}
}

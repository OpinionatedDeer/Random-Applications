package com.test.iconswitch.runtime;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;

/**
 * Per-app settings, baked into the manifest as application meta-data by apkgen.
 *
 * aapt2 compiles numeric meta-data values to integers and true/false to booleans, so they
 * are read as Number/Boolean objects, never with getString().
 */
final class Config {
    static final String TAG = "IconSwitcher";

    static final String ACTION_PREFIX = "com.test.iconswitch.action.";
    static final String ACTION_TICK = ACTION_PREFIX + "TICK";
    static final String ACTION_SWITCH = ACTION_PREFIX + "SWITCH";
    static final String ACTION_AUTO = ACTION_PREFIX + "AUTO";
    static final String ACTION_STOP = ACTION_PREFIX + "STOP";
    static final String ACTION_RESET = ACTION_PREFIX + "RESET";
    static final String ACTION_STATUS = ACTION_PREFIX + "STATUS";
    static final String ACTION_RESTORE = ACTION_PREFIX + "RESTORE";
    static final String EXTRA_INDEX = "index";
    static final String EXTRA_BOOTSTRAP = "bootstrap";

    final int appNumber;
    final int frames;
    final long intervalMs;
    final long phaseMs;
    final boolean wakeup;

    private static Config instance;

    private Config(int appNumber, int frames, long intervalMs, long phaseMs, boolean wakeup) {
        this.appNumber = appNumber;
        this.frames = frames;
        this.intervalMs = intervalMs;
        this.phaseMs = phaseMs;
        this.wakeup = wakeup;
    }

    static synchronized Config get(Context context) {
        if (instance == null) {
            instance = load(context);
        }
        return instance;
    }

    private static Config load(Context context) {
        Bundle md;
        try {
            ApplicationInfo info = context.getPackageManager().getApplicationInfo(
                    context.getPackageName(), PackageManager.GET_META_DATA);
            md = info.metaData;
        } catch (PackageManager.NameNotFoundException e) {
            throw new IllegalStateException(e);
        }
        if (md == null) {
            throw new IllegalStateException("iconswitch: manifest has no meta-data");
        }
        Config c = new Config(
                (int) number(md, "iconswitch.app"),
                (int) number(md, "iconswitch.frames"),
                number(md, "iconswitch.interval_ms"),
                number(md, "iconswitch.phase_ms"),
                bool(md, "iconswitch.wakeup"));
        if (c.frames < 2 || c.intervalMs < 10000 || c.phaseMs < 0 || c.phaseMs >= c.intervalMs) {
            throw new IllegalStateException("iconswitch: invalid meta-data " + c);
        }
        return c;
    }

    private static long number(Bundle md, String key) {
        Object value = md.get(key);
        if (value instanceof Number) {
            return ((Number) value).longValue();
        }
        if (value instanceof String) {
            return Long.parseLong((String) value);
        }
        throw new IllegalStateException("iconswitch: missing or non-numeric meta-data " + key);
    }

    private static boolean bool(Bundle md, String key) {
        Object value = md.get(key);
        if (value instanceof Boolean) {
            return (Boolean) value;
        }
        if (value instanceof String) {
            return Boolean.parseBoolean((String) value);
        }
        throw new IllegalStateException("iconswitch: missing or non-boolean meta-data " + key);
    }

    @Override
    public String toString() {
        return "app=" + appNumber + " frames=" + frames + " intervalMs=" + intervalMs
                + " phaseMs=" + phaseMs + " wakeup=" + wakeup;
    }
}

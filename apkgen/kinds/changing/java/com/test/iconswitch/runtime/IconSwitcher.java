package com.test.iconswitch.runtime;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.util.Log;

/**
 * Switches the app's launcher icon by enabling one activity-alias at a time.
 *
 * The frame to show is derived from the wall clock, frame = ((now - phase) / interval) % frames,
 * so no counter is stored and a late alarm corrects itself. Only the mode (auto/manual) and
 * the held frame are persisted.
 */
final class IconSwitcher {
    static final int INIT = -1;
    static final int NONE = -2;
    static final int MULTIPLE = -3;

    /** An alarm delivered up to this early still counts as reaching the next boundary. */
    private static final long EARLY_TOLERANCE_MS = 1000;
    private static final String PREFS = "iconswitch";
    private static final String KEY_MODE = "mode";
    private static final String KEY_HELD = "held";
    private static final String MODE_AUTO = "auto";
    private static final String MODE_MANUAL = "manual";

    private IconSwitcher() {
    }

    // ---- time ----

    /** Slot an alarm tick belongs to (tolerates slightly early delivery). */
    static long slot(Config c, long now) {
        return (now + EARLY_TOLERANCE_MS - c.phaseMs) / c.intervalMs;
    }

    /** Slot the clock is in right now, for reporting. */
    static long currentSlot(Config c, long now) {
        return (now - c.phaseMs) / c.intervalMs;
    }

    static int frameForSlot(Config c, long slot) {
        return (int) (slot % c.frames);
    }

    static long slotStart(Config c, long slot) {
        return c.phaseMs + slot * c.intervalMs;
    }

    // ---- components ----

    static String aliasName(int frame) {
        if (frame == INIT) return "IconInit";
        if (frame == NONE) return "none";
        if (frame == MULTIPLE) return "MULTIPLE";
        return "Icon" + frame;
    }

    /** Alias component; built from the app's package, never from this runtime's Java package. */
    static ComponentName alias(Context ctx, int frame) {
        String pkg = ctx.getPackageName();
        return new ComponentName(pkg, pkg + "." + aliasName(frame));
    }

    private static boolean isEnabled(PackageManager pm, ComponentName cn, boolean manifestDefault) {
        int state = pm.getComponentEnabledSetting(cn);
        return state == PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                || (state == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && manifestDefault);
    }

    /** The enabled frame, INIT, NONE, or MULTIPLE. */
    static int enabledFrame(Context ctx) {
        PackageManager pm = ctx.getPackageManager();
        int frames = Config.get(ctx).frames;
        int found = NONE;
        int count = 0;
        for (int k = INIT; k < frames; k++) {
            if (isEnabled(pm, alias(ctx, k), k == INIT)) {
                found = k;
                count++;
            }
        }
        return count > 1 ? MULTIPLE : found;
    }

    /**
     * Enable the target alias first, then disable every other one, so the launcher never sees
     * a moment with zero launcher activities. DONT_KILL_APP keeps this process alive.
     */
    static void apply(Context ctx, int target, String reason, long slotStartMs) {
        Config c = Config.get(ctx);
        PackageManager pm = ctx.getPackageManager();
        StringBuilder from = new StringBuilder();
        ComponentName targetCn = alias(ctx, target);
        boolean changed = false;
        if (!isEnabled(pm, targetCn, target == INIT)) {
            pm.setComponentEnabledSetting(targetCn, PackageManager.COMPONENT_ENABLED_STATE_ENABLED,
                    PackageManager.DONT_KILL_APP);
            changed = true;
        }
        for (int k = INIT; k < c.frames; k++) {
            if (k == target) continue;
            ComponentName cn = alias(ctx, k);
            if (isEnabled(pm, cn, k == INIT)) {
                pm.setComponentEnabledSetting(cn, PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                        PackageManager.DONT_KILL_APP);
                if (from.length() > 0) from.append('+');
                from.append(aliasName(k));
                changed = true;
            }
        }
        long now = System.currentTimeMillis();
        Log.i(Config.TAG, "event=switch app=" + c.appNumber + " reason=" + reason
                + " from=" + (from.length() == 0 ? "-" : from.toString()) + " to=" + aliasName(target)
                + " changed=" + changed + " nowMs=" + now + " slotStartMs=" + slotStartMs
                + " lateMs=" + (slotStartMs < 0 ? -1 : now - slotStartMs));
    }

    // ---- scheduling ----

    /** Auto mode: show the clock's frame now and arm the alarm for the next boundary. */
    static void tick(Context ctx, String reason) {
        Config c = Config.get(ctx);
        long slot = slot(c, System.currentTimeMillis());
        apply(ctx, frameForSlot(c, slot), reason, slotStart(c, slot));
        schedule(ctx, slotStart(c, slot + 1));
    }

    private static void schedule(Context ctx, long atMs) {
        Config c = Config.get(ctx);
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = tickIntent(ctx);  // same PendingIntent replaces any pending alarm
        if (c.wakeup) {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMs, pi);
        } else {
            am.setExact(AlarmManager.RTC, atMs, pi);
        }
        Log.i(Config.TAG, "event=schedule app=" + c.appNumber + " atMs=" + atMs + " wakeup=" + c.wakeup);
    }

    static void cancel(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        am.cancel(tickIntent(ctx));
    }

    private static PendingIntent tickIntent(Context ctx) {
        Intent intent = new Intent(ctx, SwitchReceiver.class).setAction(Config.ACTION_TICK);
        intent.addFlags(Intent.FLAG_RECEIVER_FOREGROUND);
        return PendingIntent.getBroadcast(ctx, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    // ---- modes ----

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static boolean isAuto(Context ctx) {
        return MODE_AUTO.equals(prefs(ctx).getString(KEY_MODE, null));
    }

    static boolean isManual(Context ctx) {
        return MODE_MANUAL.equals(prefs(ctx).getString(KEY_MODE, null));
    }

    static int heldFrame(Context ctx) {
        return prefs(ctx).getInt(KEY_HELD, 0) % Config.get(ctx).frames;
    }

    /** Launch/bootstrap/dashboard: start auto mode unless a frame is being held. */
    static void start(Context ctx, String reason) {
        if (prefs(ctx).getString(KEY_MODE, null) == null) {
            prefs(ctx).edit().putString(KEY_MODE, MODE_AUTO).commit();
        }
        restore(ctx, reason);
    }

    /**
     * Boot, package update, clock change or apkgen's post-install broadcast: continue the
     * previous mode; stay dormant if never started. Also repairs the alias state, e.g. when an
     * update with fewer frames removed the alias that was enabled.
     */
    static void restore(Context ctx, String reason) {
        if (isAuto(ctx)) {
            tick(ctx, reason);
        } else if (isManual(ctx)) {
            apply(ctx, heldFrame(ctx), reason + "/held", -1);
        } else {
            if (enabledFrame(ctx) != INIT) {
                apply(ctx, INIT, reason + "/init", -1);
            }
            Log.i(Config.TAG, "event=dormant app=" + Config.get(ctx).appNumber + " reason=" + reason);
        }
    }

    /** Stop the clock and show one frame until AUTO or RESET. */
    static void hold(Context ctx, int frame, String reason) {
        cancel(ctx);
        prefs(ctx).edit().putString(KEY_MODE, MODE_MANUAL).putInt(KEY_HELD, frame).commit();
        apply(ctx, frame, reason, -1);
    }

    static void auto(Context ctx) {
        prefs(ctx).edit().putString(KEY_MODE, MODE_AUTO).remove(KEY_HELD).commit();
        tick(ctx, "auto");
    }

    /** Back to the install state: INIT icon, no alarm, no saved mode. */
    static void reset(Context ctx) {
        cancel(ctx);
        PackageManager pm = ctx.getPackageManager();
        for (int k = INIT; k < Config.get(ctx).frames; k++) {  // IconInit first: enable before disable
            pm.setComponentEnabledSetting(alias(ctx, k), PackageManager.COMPONENT_ENABLED_STATE_DEFAULT,
                    PackageManager.DONT_KILL_APP);
        }
        prefs(ctx).edit().clear().commit();
        Log.i(Config.TAG, "event=reset app=" + Config.get(ctx).appNumber);
    }

    static int expectedFrame(Context ctx) {
        if (isManual(ctx)) return heldFrame(ctx);
        if (isAuto(ctx)) {
            Config c = Config.get(ctx);
            return frameForSlot(c, currentSlot(c, System.currentTimeMillis()));
        }
        return INIT;
    }

    static long nextSwitchMs(Context ctx) {
        if (!isAuto(ctx)) return -1;
        Config c = Config.get(ctx);
        return slotStart(c, currentSlot(c, System.currentTimeMillis()) + 1);
    }

    static String status(Context ctx) {
        Config c = Config.get(ctx);
        String mode = isAuto(ctx) ? MODE_AUTO : isManual(ctx) ? MODE_MANUAL : "unset";
        int enabled = enabledFrame(ctx);
        int expected = expectedFrame(ctx);
        return "app=" + c.appNumber + " mode=" + mode + " enabled=" + aliasName(enabled)
                + " expected=" + aliasName(expected) + (enabled == expected ? "" : " MISMATCH")
                + " nextMs=" + nextSwitchMs(ctx) + " intervalMs=" + c.intervalMs + " frames=" + c.frames;
    }
}

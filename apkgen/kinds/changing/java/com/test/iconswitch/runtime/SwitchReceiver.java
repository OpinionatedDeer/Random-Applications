package com.test.iconswitch.runtime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

/**
 * Handles the app's own alarm, boot and package-update broadcasts, and explicit control
 * broadcasts sent with adb, e.g.:
 *
 *   adb shell am broadcast -n PKG/com.test.iconswitch.runtime.SwitchReceiver \
 *       -a com.test.iconswitch.action.SWITCH --ei index 2
 *
 * SWITCH holds a frame (no index: next frame), AUTO resumes the clock, STOP holds the current
 * frame, RESET returns to the install state, STATUS only reports, RESTORE (sent by apkgen after
 * every install) continues the saved mode. Every broadcast replies with a status line, which
 * `am broadcast` prints as the result data; errors start with "ERROR".
 */
public final class SwitchReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent intent) {
        String action = intent.getAction();
        if (action == null) return;
        Config c = Config.get(ctx);
        switch (action) {
            case Config.ACTION_TICK:
                if (IconSwitcher.isAuto(ctx)) {
                    IconSwitcher.tick(ctx, "alarm");
                } else {
                    Log.i(Config.TAG, "event=tick-ignored app=" + c.appNumber);
                }
                break;
            case Intent.ACTION_BOOT_COMPLETED:
                IconSwitcher.restore(ctx, "boot");
                break;
            case Intent.ACTION_MY_PACKAGE_REPLACED:
                IconSwitcher.restore(ctx, "replaced");
                break;
            case Intent.ACTION_TIME_CHANGED:
                // RTC alarms keep their wall-clock trigger time: after the clock moves back the
                // pending alarm would fire that much later, so re-sync to the new time now.
                IconSwitcher.restore(ctx, "time-set");
                break;
            case Config.ACTION_RESTORE:
                IconSwitcher.restore(ctx, "install");
                break;
            case Config.ACTION_SWITCH: {
                int index = intent.getIntExtra(Config.EXTRA_INDEX, -1);
                if (index < 0) {
                    int current = IconSwitcher.enabledFrame(ctx);
                    index = current >= 0 ? (current + 1) % c.frames : 0;
                }
                if (index >= c.frames) {
                    Log.w(Config.TAG, "event=bad-index app=" + c.appNumber + " index=" + index);
                    if (isOrderedBroadcast()) {
                        setResultData("ERROR bad-index=" + index + " frames=" + c.frames + " "
                                + IconSwitcher.status(ctx));
                    }
                    return;
                }
                IconSwitcher.hold(ctx, index, "manual");
                break;
            }
            case Config.ACTION_AUTO:
                IconSwitcher.auto(ctx);
                break;
            case Config.ACTION_STOP: {
                if (!IconSwitcher.isAuto(ctx) && !IconSwitcher.isManual(ctx)) {
                    IconSwitcher.cancel(ctx);  // never started: keep the INIT icon, stay dormant
                    Log.i(Config.TAG, "event=stop app=" + c.appNumber + " dormant");
                    break;
                }
                int current = IconSwitcher.enabledFrame(ctx);
                IconSwitcher.hold(ctx, current >= 0 ? current : 0, "stop");
                break;
            }
            case Config.ACTION_RESET:
                IconSwitcher.reset(ctx);
                break;
            case Config.ACTION_STATUS:
                break;
            default:
                Log.w(Config.TAG, "event=unknown-action app=" + c.appNumber + " action=" + action);
                return;
        }
        String status = IconSwitcher.status(ctx);
        if (Config.ACTION_STATUS.equals(action)) {
            Log.i(Config.TAG, "event=status " + status);
        }
        if (isOrderedBroadcast()) {
            setResultData(status);
        }
    }
}

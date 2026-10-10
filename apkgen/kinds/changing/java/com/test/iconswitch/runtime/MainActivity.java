package com.test.iconswitch.runtime;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.format.DateFormat;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * Dashboard: compares the alias PackageManager reports as enabled with the frame the clock
 * expects, shows the icon PackageManager serves for it, and offers the same controls as the
 * adb broadcasts. Views are built in code (no layouts, no AndroidX).
 */
public final class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable refresher = new Runnable() {
        @Override
        public void run() {
            refresh();
            handler.postDelayed(this, 1000);
        }
    };
    private ImageView icon;
    private TextView info;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        IconSwitcher.start(this, "dashboard");

        int pad = dp(16);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(pad, pad, pad, pad);

        icon = new ImageView(this);
        column.addView(icon, new LinearLayout.LayoutParams(dp(96), dp(96)));

        info = new TextView(this);
        info.setTypeface(Typeface.MONOSPACE);
        info.setTextSize(14);
        info.setPadding(0, pad, 0, pad);
        column.addView(info);

        addButton(column, "Next frame (hold)", Config.ACTION_SWITCH);
        addButton(column, "Resume auto", Config.ACTION_AUTO);
        addButton(column, "Stop (hold current)", Config.ACTION_STOP);
        addButton(column, "Reset to INIT", Config.ACTION_RESET);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(column);
        setContentView(scroll);
    }

    @Override
    protected void onResume() {
        super.onResume();
        handler.post(refresher);
    }

    @Override
    protected void onPause() {
        super.onPause();
        handler.removeCallbacks(refresher);
    }

    private void addButton(LinearLayout parent, String text, final String action) {
        Button button = new Button(this);
        button.setText(text);
        button.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                // Same code path as the adb broadcasts.
                sendBroadcast(new Intent(MainActivity.this, SwitchReceiver.class).setAction(action));
                handler.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        refresh();
                    }
                }, 300);
            }
        });
        parent.addView(button);
    }

    private void refresh() {
        Config c = Config.get(this);
        int enabled = IconSwitcher.enabledFrame(this);
        int expected = IconSwitcher.expectedFrame(this);
        long next = IconSwitcher.nextSwitchMs(this);
        PackageManager pm = getPackageManager();
        Drawable d = null;
        if (enabled >= IconSwitcher.INIT) {
            try {
                d = pm.getActivityInfo(IconSwitcher.alias(this, enabled),
                        PackageManager.MATCH_DISABLED_COMPONENTS).loadIcon(pm);
            } catch (PackageManager.NameNotFoundException e) {
                d = null;
            }
        }
        icon.setImageDrawable(d);
        String mode = IconSwitcher.isAuto(this) ? "auto" : IconSwitcher.isManual(this) ? "manual (held)" : "unset";
        StringBuilder sb = new StringBuilder();
        sb.append("package   ").append(getPackageName()).append('\n');
        sb.append("app       ").append(c.appNumber).append('\n');
        sb.append("frames    ").append(c.frames).append('\n');
        sb.append("interval  ").append(c.intervalMs / 1000).append(" s").append('\n');
        sb.append("phase     ").append(c.phaseMs / 1000.0).append(" s").append('\n');
        sb.append("wakeup    ").append(c.wakeup).append('\n');
        sb.append("mode      ").append(mode).append('\n');
        sb.append("enabled   ").append(IconSwitcher.aliasName(enabled)).append("   (PackageManager)").append('\n');
        sb.append("expected  ").append(IconSwitcher.aliasName(expected)).append("   (clock)").append('\n');
        if (enabled != expected) {
            sb.append("MISMATCH").append('\n');
        }
        if (next > 0) {
            long seconds = Math.max(0, (next - System.currentTimeMillis()) / 1000);
            sb.append("next      ").append(DateFormat.format("HH:mm:ss", next))
                    .append("  (in ").append(seconds).append(" s)").append('\n');
        }
        info.setText(sb.toString());
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}

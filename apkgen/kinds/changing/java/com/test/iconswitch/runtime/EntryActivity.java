package com.test.iconswitch.runtime;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.util.Log;

/**
 * Invisible trampoline that every launcher alias points at.
 *
 * It makes sure switching is running, then opens the dashboard in its own task (never rooted
 * at an alias, which may be disabled at the next switch) and finishes. Started with
 * `--ez bootstrap true` (apkgen --launch) it only starts switching. Theme.NoDisplay requires
 * finish() before onCreate returns.
 */
public final class EntryActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent intent = getIntent();
        boolean bootstrap = intent.getBooleanExtra(Config.EXTRA_BOOTSTRAP, false);
        ComponentName via = intent.getComponent();
        Log.i(Config.TAG, "event=entry app=" + Config.get(this).appNumber
                + " via=" + (via == null ? "?" : via.getShortClassName())
                + " enabled=" + IconSwitcher.aliasName(IconSwitcher.enabledFrame(this))
                + " bootstrap=" + bootstrap);
        IconSwitcher.start(this, bootstrap ? "bootstrap" : "entry");
        if (!bootstrap) {
            startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        }
        finish();
    }
}

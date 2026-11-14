package ai.esteef.lacklusterplus;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.UiModeManager;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/**
 * Lackluster Plus+ (Philibert TV, by Esteef.Ai) for Fire TV and Android TV.
 *
 * The app is the Lackluster Plus+ web page in a full-screen frame. What it adds:
 *   - it asks for the server address once and remembers it;
 *   - it tells the page it is a TV (the words LacklusterPlusTV in the user agent), so the page signs in with a
 *     code and turns remote mode on;
 *   - the remote's Back goes to the page first (window.tvBack()); the app only leaves when the page has nothing
 *     left to close;
 *   - OK and Play/Pause are passed to the page as the keys it listens for;
 *   - Menu opens Reload / Change server address.
 */
public class MainActivity extends Activity {

    static final String PREFS = "lacklusterplus";
    static final String KEY_SERVER = "server";
    static final String KEY_WIDTH = "page_width";
    static final int[] WIDTHS = {960, 1280, 1600};      // how wide the page thinks the TV is; wider = everything smaller
    static final String[] WIDTH_NAMES = {"Large", "Normal", "Small"};
    static final String UA_MARK = "LacklusterPlusTV/1.0";

    static final int BG = Color.parseColor("#0A0C10");
    static final int RAISED = Color.parseColor("#14171F");
    static final int LINE = Color.parseColor("#262B36");
    static final int TEXT = Color.parseColor("#F4F5F9");
    static final int MUTED = Color.parseColor("#8B90A3");
    static final int BLUE = Color.parseColor("#3B6CFF");
    static final int CYAN = Color.parseColor("#4CE0E8");
    static final int RED = Color.parseColor("#E8304C");

    FrameLayout root;
    WebView web;
    LinearLayout panel;            // the address / error screen, drawn over the page
    TextView panelMessage;
    EditText addressBox;
    Button connectButton;

    View customView;               // a video the page put in native full screen
    WebChromeClient.CustomViewCallback customViewCallback;

    String server = "";            // e.g. http://192.168.0.184:9191 (no trailing slash)
    boolean pageShown;             // a page from the server is on screen
    boolean loadFailed;
    long lastBack;

    // ───────────────────────────────────────────────────────────── start-up

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        setContentView(root);

        web = new WebView(this);
        web.setBackgroundColor(BG);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setUpWeb();
        buildPanel();
        fitPage(getSharedPreferences(PREFS, MODE_PRIVATE).getInt(KEY_WIDTH, 1280));

        server = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, "");
        if (server.length() == 0) {
            showPanel("Where is your Lackluster Plus+ server?", getString(R.string.default_server));
        } else {
            load();
        }
    }

    /**
     * A Fire TV reports a 960 x 540 screen to a web page, which makes this page far too big. So on a TV the frame is
     * made larger than the screen and drawn reduced: the page lays itself out for a screen `width` wide.
     */
    void fitPage(int width) {
        if (!isTv()) return;
        android.util.DisplayMetrics m = new android.util.DisplayMetrics();
        getWindowManager().getDefaultDisplay().getRealMetrics(m);
        float scale = (m.widthPixels / m.density) / width;          // e.g. 960 / 1280 = 0.75
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(Math.round(m.widthPixels / scale), Math.round(m.heightPixels / scale));
        web.setLayoutParams(lp);
        web.setPivotX(0);
        web.setPivotY(0);
        web.setScaleX(scale);
        web.setScaleY(scale);
    }

    void pickSize() {
        final SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        int now = prefs.getInt(KEY_WIDTH, 1280), at = 1;
        for (int i = 0; i < WIDTHS.length; i++) if (WIDTHS[i] == now) at = i;
        new AlertDialog.Builder(this)
                .setTitle("Size of everything on screen")
                .setSingleChoiceItems(WIDTH_NAMES, at, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        prefs.edit().putInt(KEY_WIDTH, WIDTHS[which]).apply();
                        fitPage(WIDTHS[which]);
                        d.dismiss();
                    }
                })
                .show();
    }

    boolean isTv() {
        UiModeManager ui = (UiModeManager) getSystemService(Context.UI_MODE_SERVICE);
        if (ui != null && ui.getCurrentModeType() == Configuration.UI_MODE_TYPE_TELEVISION) return true;
        return getPackageManager().hasSystemFeature("amazon.hardware.fire_tv")
                || getPackageManager().hasSystemFeature("android.software.leanback");
    }

    void setUpWeb() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setSupportMultipleWindows(false);          // nothing ever opens a second window
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        if (isTv()) s.setUserAgentString(s.getUserAgentString() + " " + UA_MARK);
        CookieManager.getInstance().setAcceptCookie(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                return false;                        // every link stays in this frame
            }

            @Override
            public void onPageStarted(WebView v, String url, android.graphics.Bitmap icon) {
                if (!"about:blank".equals(url)) loadFailed = false;   // failed() loads a blank page: that is not a new try
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (loadFailed || "about:blank".equals(url)) return;
                pageShown = true;
                hidePanel();
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) failed(Build.VERSION.SDK_INT >= 23 ? String.valueOf(err.getDescription()) : "");
            }

            @Override
            @SuppressWarnings("deprecation")
            public void onReceivedError(WebView v, int code, String description, String failingUrl) {
                if (Build.VERSION.SDK_INT < 23) failed(description);
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onShowCustomView(View view, CustomViewCallback callback) {
                if (customView != null) { callback.onCustomViewHidden(); return; }
                customView = view;
                customViewCallback = callback;
                root.addView(view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            }

            @Override
            public void onHideCustomView() {
                if (customView == null) return;
                root.removeView(customView);
                customView = null;
                if (customViewCallback != null) customViewCallback.onCustomViewHidden();
                customViewCallback = null;
                web.requestFocus();
            }
        });
    }

    void load() {
        loadFailed = false;
        web.loadUrl(server + "/");
        web.requestFocus();
    }

    void failed(String why) {
        loadFailed = true;
        pageShown = false;
        web.loadUrl("about:blank");
        String more = (why == null || why.length() == 0) ? "" : "\n(" + why + ")";
        showPanel("Cannot reach " + server + more + "\nCheck the address, and that this device is on the same network.", server);
    }

    // ───────────────────────────────────────────────────────────── the address screen

    static String cleanAddress(String typed) {
        String a = typed == null ? "" : typed.trim();
        if (a.length() == 0) return "";
        if (!a.matches("(?i)^https?://.*")) a = "http://" + a;
        while (a.endsWith("/")) a = a.substring(0, a.length() - 1);
        Uri u = Uri.parse(a);
        if (u.getHost() == null || u.getHost().length() == 0) return "";
        return a;
    }

    int dp(int v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    GradientDrawable box(int fill, int stroke, int strokeDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(10));
        g.setStroke(dp(strokeDp), stroke);
        return g;
    }

    /** A background that shows a bright outline while the remote's highlight is on the view. */
    StateListDrawable focusable(int fill) {
        StateListDrawable d = new StateListDrawable();
        d.addState(new int[]{android.R.attr.state_focused}, box(fill, CYAN, 3));
        d.addState(new int[]{}, box(fill, LINE, 1));
        return d;
    }

    void buildPanel() {
        panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setBackgroundColor(BG);
        panel.setPadding(dp(48), dp(24), dp(48), dp(24));

        TextView name = new TextView(this);
        name.setText(getString(R.string.app_name));
        name.setTextColor(TEXT);
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 34);
        name.setTypeface(Typeface.DEFAULT_BOLD);
        name.setGravity(Gravity.CENTER);
        panel.addView(name);

        TextView by = new TextView(this);
        by.setText(getString(R.string.byline));
        by.setTextColor(MUTED);
        by.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        by.setGravity(Gravity.CENTER);
        panel.addView(by);

        panelMessage = new TextView(this);
        panelMessage.setTextColor(TEXT);
        panelMessage.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        panelMessage.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams mp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        mp.setMargins(0, dp(28), 0, dp(14));
        panel.addView(panelMessage, mp);

        addressBox = new EditText(this);
        addressBox.setSingleLine(true);
        addressBox.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addressBox.setImeOptions(EditorInfo.IME_ACTION_GO);
        addressBox.setTextColor(TEXT);
        addressBox.setHintTextColor(MUTED);
        addressBox.setHint("http://192.168.0.10:9191");
        addressBox.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        addressBox.setGravity(Gravity.CENTER);
        addressBox.setBackground(focusable(RAISED));
        addressBox.setPadding(dp(18), dp(12), dp(18), dp(12));
        addressBox.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int action, KeyEvent e) {
                connect();
                return true;
            }
        });
        panel.addView(addressBox, new LinearLayout.LayoutParams(dp(460), ViewGroup.LayoutParams.WRAP_CONTENT));

        connectButton = new Button(this);
        connectButton.setText("Connect");
        connectButton.setAllCaps(false);
        connectButton.setTextColor(TEXT);
        connectButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        connectButton.setBackground(focusable(BLUE));
        connectButton.setPadding(dp(34), dp(10), dp(34), dp(10));
        connectButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connect();
            }
        });
        LinearLayout.LayoutParams bp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        bp.setMargins(0, dp(18), 0, 0);
        panel.addView(connectButton, bp);

        TextView hint = new TextView(this);
        hint.setText("The Menu button on the remote brings this screen back.");
        hint.setTextColor(MUTED);
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        hint.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams hp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hp.setMargins(0, dp(26), 0, 0);
        panel.addView(hint, hp);

        panel.setVisibility(View.GONE);
        root.addView(panel, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    void showPanel(String message, String address) {
        panelMessage.setText(message);
        addressBox.setText(address);
        addressBox.setSelection(addressBox.getText().length());
        panel.setVisibility(View.VISIBLE);
        connectButton.requestFocus();          // OK connects straight away; Up reaches the box to change it
    }

    void hidePanel() {
        if (panel.getVisibility() != View.VISIBLE) return;
        panel.setVisibility(View.GONE);
        web.requestFocus();
    }

    boolean panelOpen() {
        return panel.getVisibility() == View.VISIBLE;
    }

    void connect() {
        String a = cleanAddress(addressBox.getText().toString());
        if (a.length() == 0) {
            panelMessage.setText("That is not an address. It looks like http://192.168.0.10:9191");
            return;
        }
        server = a;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, a).apply();
        panelMessage.setText("Connecting to " + a + " ...");
        load();
    }

    void menu() {
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.app_name))
                .setItems(new String[]{"Reload", "Size of everything on screen", "Change server address", "Leave the app", "Cancel"}, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        if (which == 0) load();
                        else if (which == 1) pickSize();
                        else if (which == 2) showPanel("Where is your Lackluster Plus+ server?", server);
                        else if (which == 3) finish();
                    }
                })
                .show();
    }

    // ───────────────────────────────────────────────────────────── the remote

    void sendKeyToPage(String key) {
        web.evaluateJavascript("(function(){var t=document.activeElement||document.body;"
                + "t.dispatchEvent(new KeyboardEvent('keydown',{key:'" + key + "',bubbles:true,cancelable:true}));})()", null);
    }

    void back() {
        if (customView != null) {                              // a native full-screen video: leave that first
            if (customViewCallback != null) customViewCallback.onCustomViewHidden();
            root.removeView(customView);
            customView = null;
            customViewCallback = null;
            web.requestFocus();
            return;
        }
        if (panelOpen()) {
            if (pageShown) hidePanel(); else finish();
            return;
        }
        // the page closes its own top-most thing and answers true; false means nothing was open
        web.evaluateJavascript("(function(){try{return !!(window.tvBack&&window.tvBack());}catch(e){return false;}})()",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String v) {
                        if ("true".equals(v)) return;
                        long now = System.currentTimeMillis();
                        if (now - lastBack < 2500) {
                            finish();
                        } else {
                            lastBack = now;
                            Toast.makeText(MainActivity.this, "Press Back again to leave", Toast.LENGTH_SHORT).show();
                        }
                    }
                });
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int code = e.getKeyCode();
        boolean down = e.getAction() == KeyEvent.ACTION_DOWN;
        boolean first = down && e.getRepeatCount() == 0;

        if (code == KeyEvent.KEYCODE_BACK) {
            if (e.getAction() == KeyEvent.ACTION_UP && !e.isCanceled()) back();
            return true;
        }
        if (code == KeyEvent.KEYCODE_MENU) {
            if (e.getAction() == KeyEvent.ACTION_UP) menu();
            return true;
        }
        if (panelOpen() || customView != null) return super.dispatchKeyEvent(e);

        // from here on the page has the keys
        if (code == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE || code == KeyEvent.KEYCODE_MEDIA_PLAY || code == KeyEvent.KEYCODE_MEDIA_PAUSE) {
            if (first) sendKeyToPage(code == KeyEvent.KEYCODE_MEDIA_PLAY ? "MediaPlay" : code == KeyEvent.KEYCODE_MEDIA_PAUSE ? "MediaPause" : "MediaPlayPause");
            return true;
        }
        if (code == KeyEvent.KEYCODE_DPAD_CENTER || code == KeyEvent.KEYCODE_NUMPAD_ENTER || code == KeyEvent.KEYCODE_BUTTON_A) {
            // the remote's OK reaches the page as Enter, which is what the page listens for
            return super.dispatchKeyEvent(new KeyEvent(e.getDownTime(), e.getEventTime(), e.getAction(), KeyEvent.KEYCODE_ENTER,
                    e.getRepeatCount(), e.getMetaState(), e.getDeviceId(), 0, e.getFlags(), e.getSource()));
        }
        return super.dispatchKeyEvent(e);
    }

    // ───────────────────────────────────────────────────────────── coming and going

    @Override
    protected void onPause() {
        super.onPause();
        web.onPause();                          // stops the picture and sound when the app is left
        CookieManager.getInstance().flush();    // keep the sign-in for next time
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onDestroy() {
        root.removeView(web);
        web.destroy();
        super.onDestroy();
    }
}

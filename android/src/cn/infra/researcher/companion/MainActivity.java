package cn.infra.researcher.companion;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
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
import android.widget.LinearLayout;
import android.widget.TextView;
import java.net.URI;

/** Same-Wi-Fi client. No JavaScript bridge, system commands or model keys. */
public class MainActivity extends Activity {
    private LinearLayout root, welcome, toolbar;
    private WebView web;
    private EditText address;
    private TextView status;
    private URI endpoint;
    private ValueCallback<Uri[]> fileCallback;
    private int dp(int n) { return (int)(n * getResources().getDisplayMetrics().density + .5f); }
    private TextView text(String content, int size) {
        TextView t = new TextView(this); t.setText(content); t.setTextSize(size); t.setTextColor(Color.rgb(48,68,87)); t.setPadding(0,dp(8),0,dp(8)); return t;
    }
    private Button button(String title) { Button b = new Button(this); b.setText(title); b.setAllCaps(false); return b; }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); getWindow().setStatusBarColor(Color.WHITE); getWindow().setNavigationBarColor(Color.WHITE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.WHITE); setContentView(root);
        toolbar = new LinearLayout(this); toolbar.setPadding(dp(8),0,dp(8),0);
        Button home = button("连接设置"), reload = button("刷新"), browser = button("浏览器打开");
        toolbar.addView(home); toolbar.addView(reload); toolbar.addView(browser); root.addView(toolbar); toolbar.setVisibility(View.GONE);
        welcome = new LinearLayout(this); welcome.setOrientation(LinearLayout.VERTICAL); welcome.setPadding(dp(24),dp(32),dp(24),dp(20));
        welcome.addView(text("Infra 研究室",28)); welcome.addView(text("从手机，继续你的研究。",18));
        welcome.addView(text("1. 电脑和手机连接同一 Wi-Fi。\n2. 电脑开启“手机连接”。\n3. 填入电脑显示的局域网地址，连接后输入六位配对码。",14));
        address = new EditText(this); address.setSingleLine(true); address.setHint("http://192.168.1.5:端口/"); address.setInputType(17);
        address.setText(getPreferences(MODE_PRIVATE).getString("address","")); welcome.addView(address);
        Button connect=button("连接研究室"); welcome.addView(connect); status=text("只控制研究室的聊天、研究、报告和学习进度。电脑需保持运行。",13); welcome.addView(status);
        welcome.addView(text("安装包不提供远程桌面。局域网采用 HTTP，请使用信任的 Wi-Fi。导出文件可通过“浏览器打开”完成。",12)); root.addView(welcome);
        web=new WebView(this); web.setBackgroundColor(Color.WHITE); root.addView(web,new LinearLayout.LayoutParams(-1,0,1)); web.setVisibility(View.GONE);
        WebSettings s=web.getSettings(); s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true); s.setAllowFileAccess(false); s.setAllowContentAccess(false); s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW); s.setSupportMultipleWindows(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest req){
                if(sameOrigin(req.getUrl().toString())) return false;
                if(req.hasGesture() && "https".equals(req.getUrl().getScheme())) {
                    new AlertDialog.Builder(MainActivity.this).setMessage("在浏览器打开这个外部链接？\n"+req.getUrl()).setPositiveButton("打开",(d,w)->openBrowser(req.getUrl())).setNegativeButton("取消",null).show();
                }
                return true;
            }
            @Override public void onReceivedError(WebView v,WebResourceRequest req,WebResourceError error){if(req.isForMainFrame())showWelcome("无法连接电脑。检查电脑是否开启手机连接、Wi-Fi、防火墙和地址端口。");}
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> callback,FileChooserParams params){
                if(fileCallback!=null)fileCallback.onReceiveValue(null); fileCallback=callback;
                Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT); i.addCategory(Intent.CATEGORY_OPENABLE); i.setType("*/*");
                try{startActivityForResult(i,100);}catch(Exception e){fileCallback.onReceiveValue(null);fileCallback=null;} return true;
            }
        });
        connect.setOnClickListener(v->connect()); home.setOnClickListener(v->{web.stopLoading();showWelcome("更换电脑地址后，点击连接。配对码只在电脑网页内填写。");});
        reload.setOnClickListener(v->web.reload()); browser.setOnClickListener(v->{if(endpoint!=null)openBrowser(Uri.parse(endpoint.toString()));});
    }
    private void connect(){
        try{endpoint=AddressPolicy.parse(address.getText().toString());}catch(Exception e){status.setText("请输入电脑显示的地址，例如 http://192.168.1.5:54321/。只支持同 Wi-Fi 私有 IPv4 地址。");return;}
        getPreferences(MODE_PRIVATE).edit().putString("address",endpoint.toString()).apply(); welcome.setVisibility(View.GONE);toolbar.setVisibility(View.VISIBLE);web.setVisibility(View.VISIBLE);web.loadUrl(endpoint.toString());
    }
    private boolean sameOrigin(String value){try{URI u=new URI(value);return endpoint!=null&&endpoint.getScheme().equals(u.getScheme())&&endpoint.getHost().equals(u.getHost())&&endpoint.getPort()==u.getPort();}catch(Exception e){return false;}}
    private void showWelcome(String message){web.setVisibility(View.GONE);toolbar.setVisibility(View.GONE);welcome.setVisibility(View.VISIBLE);status.setText(message);}
    private void openBrowser(Uri uri){try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception e){new AlertDialog.Builder(this).setMessage("没有可用浏览器。").setPositiveButton("确定",null).show();}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==100&&fileCallback!=null){fileCallback.onReceiveValue(result==RESULT_OK&&data!=null?new Uri[]{data.getData()}:null);fileCallback=null;}}
    @Override public void onBackPressed(){if(web.getVisibility()==View.VISIBLE){if(web.canGoBack())web.goBack();else showWelcome("返回连接设置。");}else super.onBackPressed();}
    @Override protected void onPause(){super.onPause();web.onPause();CookieManager.getInstance().flush();}
    @Override protected void onResume(){super.onResume();if(web!=null)web.onResume();}
    @Override protected void onDestroy(){if(fileCallback!=null)fileCallback.onReceiveValue(null);web.destroy();super.onDestroy();}
}

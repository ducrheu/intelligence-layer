// WebView2 启动动画外壳（C# 5，用系统 csc 直接编译）
//
// 编译：
//   CSC=/mnt/c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe
//   "$CSC" /nologo /target:winexe /platform:x64 /out:SplashLauncher.exe \
//     /r:Microsoft.Web.WebView2.Core.dll /r:Microsoft.Web.WebView2.WinForms.dll \
//     /r:System.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll SplashLauncher.cs
//
// 同目录需要：Microsoft.Web.WebView2.Core.dll、Microsoft.Web.WebView2.WinForms.dll
//            （NuGet 的 lib/net462/）、WebView2Loader.dll（runtimes/win-x64/native/）
//            以及 <name>.ini 和 boot/<name>/index.html
// 取材与验收详见 references/native-launcher-integration.md
//
// 用法：SplashLauncher.exe hermes | openclaw
// 动画页播完时调用 window.chrome.webview.postMessage('done')。

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

class SplashLauncher : Form
{
    private WebView2 web;
    private Label bootLabel;
    private string targetExe, targetArgs, targetDir, htmlUri;
    private bool targetStarted = false;
    private Timer warmTimer;
    private Timer watchdog;

    [STAThread]
    static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SplashLauncher(args));
    }

    public SplashLauncher(string[] args)
    {
        string name = args.Length > 0 ? args[0] : "hermes";
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        Dictionary<string, string> cfg = ReadIni(Path.Combine(baseDir, name + ".ini"));

        targetExe  = Get(cfg, "exe");
        targetArgs = Get(cfg, "args");
        targetDir  = Get(cfg, "dir");
        htmlUri    = Get(cfg, "html");

        int warmMs = 2500;
        string warmS = Get(cfg, "warm");
        if (!string.IsNullOrEmpty(warmS)) { int.TryParse(warmS, out warmMs); }
        if (warmMs < 0) warmMs = 0;

        Color bg = Color.FromArgb(5, 8, 20);

        this.FormBorderStyle = FormBorderStyle.None;
        this.StartPosition = FormStartPosition.Manual;
        this.Bounds = Screen.PrimaryScreen.Bounds;
        this.TopMost = true;            // 盖住目标应用抢跑的窗口
        this.ShowInTaskbar = false;
        this.BackColor = bg;

        // 首屏字标：WebView2 初始化那 ~1 s 不要留黑
        bootLabel = new Label();
        bootLabel.Text = Get(cfg, "label");
        if (string.IsNullOrEmpty(bootLabel.Text)) bootLabel.Text = "DeepSeek";
        bootLabel.ForeColor = Color.FromArgb(226, 238, 255);
        bootLabel.Font = new Font("Segoe UI", 40F, FontStyle.Bold);
        bootLabel.TextAlign = ContentAlignment.MiddleCenter;
        bootLabel.Dock = DockStyle.Fill;
        bootLabel.BackColor = bg;
        this.Controls.Add(bootLabel);

        web = new WebView2();
        web.Dock = DockStyle.Fill;
        web.DefaultBackgroundColor = bg;
        web.Visible = false;
        this.Controls.Add(web);

        this.Load += OnLoad;

        // 预热：动画还在播的时候就把目标拉起来
        warmTimer = new Timer();
        warmTimer.Interval = warmMs;
        warmTimer.Tick += OnWarm;
        warmTimer.Start();

        // watchdog：页面没加载出来 / 没报信也要能拉起目标
        watchdog = new Timer();
        watchdog.Interval = 12000;
        watchdog.Tick += OnWatchdog;
        watchdog.Start();
    }

    private async void OnLoad(object sender, EventArgs e)
    {
        try
        {
            string udf = Path.Combine(Path.GetTempPath(), "splash-wv2");
            CoreWebView2Environment env = await CoreWebView2Environment.CreateAsync(null, udf);
            await web.EnsureCoreWebView2Async(env);

            CoreWebView2Settings st = web.CoreWebView2.Settings;
            st.AreDefaultContextMenusEnabled = false;
            st.AreDevToolsEnabled = false;
            st.IsStatusBarEnabled = false;
            st.IsZoomControlEnabled = false;

            web.CoreWebView2.WebMessageReceived += OnMessage;
            web.CoreWebView2.NavigationCompleted += OnNavDone;

            string uri = htmlUri;
            if (uri.Length > 0 && uri.IndexOf("://") < 0) uri = new Uri(uri).AbsoluteUri;
            web.CoreWebView2.Navigate(uri);
        }
        catch (Exception)
        {
            // WebView2 不可用（运行时缺失等）也必须保证目标能被拉起
            StartTarget();
            this.Close();
        }
    }

    private void OnNavDone(object sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        web.Visible = true;
        bootLabel.Visible = false;
    }

    private void OnMessage(object sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        string msg = null;
        try { msg = e.TryGetWebMessageAsString(); }
        catch (Exception) { }
        if (msg == "done") { StartTarget(); this.Close(); }
    }

    private void OnWarm(object sender, EventArgs e)
    {
        warmTimer.Stop();
        StartTarget();
    }

    private void OnWatchdog(object sender, EventArgs e)
    {
        watchdog.Stop();
        StartTarget();
        this.Close();
    }

    private void StartTarget()
    {
        if (targetStarted) return;
        targetStarted = true;
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo(targetExe);
            if (!string.IsNullOrEmpty(targetArgs)) psi.Arguments = targetArgs;
            if (!string.IsNullOrEmpty(targetDir))  psi.WorkingDirectory = targetDir;
            psi.UseShellExecute = false;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("启动失败：" + ex.Message, "SplashLauncher");
        }
    }

    // 扁平 key=value，# 或 ; 开头为注释；大小写不敏感。不做 section 解析。
    private static Dictionary<string, string> ReadIni(string path)
    {
        Dictionary<string, string> d = new Dictionary<string, string>();
        try
        {
            if (!File.Exists(path)) return d;
            string[] lines = File.ReadAllLines(path);
            foreach (string raw in lines)
            {
                string line = raw.Trim();
                if (line.Length == 0 || line[0] == '#' || line[0] == ';') continue;
                int eq = line.IndexOf('=');
                if (eq <= 0) continue;
                d[line.Substring(0, eq).Trim().ToLowerInvariant()] = line.Substring(eq + 1).Trim();
            }
        }
        catch (Exception) { }
        return d;
    }

    private static string Get(Dictionary<string, string> d, string k)
    {
        string v;
        return d.TryGetValue(k, out v) ? v : "";
    }
}

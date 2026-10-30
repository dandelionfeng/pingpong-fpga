using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

static class V6Program {
    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        if(args.Contains("--batch")) {
            try { using(var app = new TestWindow(args)) app.RunBatch(); }
            catch(Exception ex) { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "batch-error.txt"), ex.ToString()); Environment.ExitCode = 1; }
            return;
        }
        try { Application.Run(new TestWindow(args)); }
        catch(Exception ex) { MessageBox.Show(ex.ToString(), "V6 抛球测试启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }
}

// Public metric contract: +Z is world vertical; contact is not a metric endpoint.
// Keep the backend velocity/chord fields for compatibility, but derive the two
// displayed toss measurements from the same explicit release and apex points.
static class TossMetrics {
    public const string Version = "release-apex-world-z-v1";
    static object Get(object value, string key) { var d = value as Dictionary<string, object>; object v; return d != null && d.TryGetValue(key, out v) ? v : null; }
    static double[] Point(object value) {
        var a = value as object[];
        if(a == null || a.Length != 3 || a.Any(v => v == null)) return null;
        try { var p = a.Select(Convert.ToDouble).ToArray(); return p.All(v => !Double.IsNaN(v) && !Double.IsInfinity(v)) ? p : null; } catch { return null; }
    }
    public static Dictionary<string, object> FromEvent(object ev) {
        var result = new Dictionary<string, object> { { "definition", Version }, { "valid", false }, { "height_m", null }, { "angle_from_vertical_deg", null }, { "contact_used_as_endpoint", false } };
        var release = Point(Get(ev, "release_world_m")); var apex = Point(Get(ev, "apex_world_m"));
        if(!Object.Equals(Get(ev, "fit_valid"), true) || release == null || apex == null) return result;
        double h = apex[2] - release[2]; if(h <= 0 || Double.IsInfinity(h)) return result;
        double dx = apex[0] - release[0], dy = apex[1] - release[1];
        double angle = Math.Atan2(Math.Sqrt(dx * dx + dy * dy), h) * 180 / Math.PI;
        if(Double.IsNaN(angle) || Double.IsInfinity(angle)) return result;
        result["valid"] = true; result["height_m"] = h; result["angle_from_vertical_deg"] = angle;
        result["release_world_m"] = release; result["apex_world_m"] = apex;
        result["height_formula"] = "apex.z - release.z";
        result["angle_formula"] = "atan2(hypot(apex.x-release.x,apex.y-release.y),apex.z-release.z)";
        return result;
    }
}

class TestWindow : Form {
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false);
    readonly string root, appDir, runtime, exe, config, calibration;
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = Int32.MaxValue, RecursionLimit = 512 };
    readonly TextBox video = new TextBox { Dock = DockStyle.Fill, Name = "videoPath" };
    readonly Button choose = new Button { Text = "选择 AVI 视频…", AutoSize = true, Name = "chooseVideo" };
    readonly Button run = new Button { Text = "开始测试", Width = 140, Height = 42, Name = "startTest" };
    readonly Button stop = new Button { Text = "停止", Width = 80, Height = 42, Enabled = false };
    readonly Button sample = new Button { Text = "查看已验证样例", AutoSize = true, Name = "viewSample" };
    readonly Button replay = new Button { Text = "查看本次回放", AutoSize = true, Enabled = false, Name = "viewResult" };
    readonly Button folder = new Button { Text = "打开结果文件夹", AutoSize = true, Enabled = false };
    readonly ProgressBar progress = new ProgressBar { Dock = DockStyle.Fill, Minimum = 0, Maximum = 100 };
    readonly Label status = new Label { Dock = DockStyle.Fill, AutoSize = true, Text = "就绪：选择视频后点击开始测试。", Name = "testStatus" };
    readonly Label resultTitle = new Label { AutoSize = true, Text = "测试结果", Font = new Font("Microsoft YaHei UI", 12, FontStyle.Bold) };
    readonly Label height = new Label { Text = "—", AutoSize = true, Font = new Font("Microsoft YaHei UI", 23, FontStyle.Bold), ForeColor = Color.FromArgb(0, 118, 115), Name = "heightValue" };
    readonly Label velocity = new Label { Text = "—", AutoSize = true, Font = new Font("Microsoft YaHei UI", 23, FontStyle.Bold), ForeColor = Color.FromArgb(0, 118, 115), Name = "velocityValue" };
    readonly Label chord = new Label { Text = "—", AutoSize = true, Font = new Font("Microsoft YaHei UI", 23, FontStyle.Bold), ForeColor = Color.FromArgb(0, 118, 115), Name = "chordValue" };
    readonly TextBox log = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Name = "testLog" };
    readonly BackgroundWorker worker = new BackgroundWorker { WorkerReportsProgress = true };
    volatile bool cancelled;
    Process child;
    string latestReplay, latestResult;
    readonly string[] args;
    readonly bool onlineTeso, sequentialTeso, maskRelease;

    public TestWindow(string[] arguments) {
        args = arguments;
        maskRelease = !args.Contains("--legacy-release");
        sequentialTeso = args.Contains("--teso-first");
        onlineTeso = sequentialTeso || args.Contains("--teso") || Path.GetFileName(Application.ExecutablePath).StartsWith("TESO", StringComparison.OrdinalIgnoreCase);
        appDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        root = Directory.GetParent(appDir).Parent.FullName;
        runtime = Path.Combine(root, "config");
        exe = Path.Combine(appDir, "pipeline_cli.exe");
        config = Path.Combine(runtime, "model-config-v6.json");
        calibration = Path.Combine(runtime, "calibration.json");
        Text = sequentialTeso ? "V6 抛球测试 · TESO先行顺序模拟" : onlineTeso ? "V6 抛球测试 · CPU 在线 TESO" : "V6 抛球测试"; Name = "V6ThrowTest"; Width = 1000; Height = 740; MinimumSize = new Size(850, 650);
        StartPosition = FormStartPosition.CenterScreen; BackColor = Color.White; Font = new Font("Microsoft YaHei UI", 10);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 10 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 54));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 94));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        Controls.Add(layout);
        layout.Controls.Add(new Label { Text = "V6 球模型 · 抛球高度与角度测试", Font = new Font(Font.FontFamily, 18, FontStyle.Bold), AutoSize = true }, 0, 0);
        layout.Controls.Add(new Label { Text = "球：V6 Round2；手/拍：三合一。离手：" + (maskRelease ? "运动转折拟合（自动）" : "旧手框对照") + "；沿用当前标定。\n视频：左右拼接 2560×720、MJPEG 编码 AVI、小于 128 MiB；建议每段一次完整抛球。", Dock = DockStyle.Fill }, 0, 1);
        var input = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
        input.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); input.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        input.Controls.Add(video, 0, 0); input.Controls.Add(choose, 1, 0); layout.Controls.Add(input, 0, 2);
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        buttons.Controls.AddRange(new Control[] { run, stop, sample }); layout.Controls.Add(buttons, 0, 3);
        layout.Controls.Add(progress, 0, 4); layout.Controls.Add(status, 0, 5); layout.Controls.Add(resultTitle, 0, 6);
        var metrics = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 2 };
        for(int i = 0; i < 3; ++i) metrics.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33f));
        metrics.Controls.Add(new Label { Text = "抛球高度：最高点至离手水平面", AutoSize = true }, 0, 0);
        metrics.Controls.Add(new Label { Text = "抛球角度：离手—最高点与竖直", AutoSize = true }, 1, 0);
        metrics.Controls.Add(new Label { Text = "诊断：出手瞬间速度偏角", AutoSize = true }, 2, 0);
        velocity.ForeColor = Color.DimGray; velocity.Font = new Font("Microsoft YaHei UI", 18);
        metrics.Controls.Add(height, 0, 1); metrics.Controls.Add(chord, 1, 1); metrics.Controls.Add(velocity, 2, 1); layout.Controls.Add(metrics, 0, 7);
        var outputButtons = new FlowLayoutPanel { Dock = DockStyle.Fill };
        outputButtons.Controls.AddRange(new Control[] { replay, folder }); layout.Controls.Add(outputButtons, 0, 8); layout.Controls.Add(log, 0, 9);
        video.Text = ""; sample.Visible = false;
        choose.Click += delegate { using(var dialog = new OpenFileDialog { Filter = "MJPEG AVI 视频 (*.avi)|*.avi", CheckFileExists = true, Title = "选择左右拼接测试视频" }) {
            if(dialog.ShowDialog(this) == DialogResult.OK) video.Text = dialog.FileName; } };
        run.Click += delegate { StartTest(); }; stop.Click += delegate { cancelled = true; try { if(child != null && !child.HasExited) child.Kill(); } catch { } };
        sample.Click += delegate { OpenSample(); };
        replay.Click += delegate { OpenBrowser(latestReplay); }; folder.Click += delegate { if(Directory.Exists(latestResult)) Process.Start("explorer.exe", Quote(latestResult)); };
        worker.DoWork += Work; worker.ProgressChanged += Progress;
        worker.RunWorkerCompleted += Completed;
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if(worker.IsBusy) {
            if(MessageBox.Show(this, "测试正在运行，是否停止并关闭？", "V6 抛球测试", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) { e.Cancel = true; return; }
            cancelled = true; try { if(child != null && !child.HasExited) child.Kill(); } catch { } } };
        Shown += delegate {
            int resultArg = Array.IndexOf(args, "--result");
            if(resultArg >= 0 && resultArg + 1 < args.Length) { LoadResult(args[resultArg + 1]); return; }
            int videoArg = Array.IndexOf(args, "--video");
            if(videoArg >= 0 && videoArg + 1 < args.Length) { video.Text = args[videoArg + 1]; StartTest(); }
            else if(args.Contains("--view")) OpenSample();
        };
        if(sequentialTeso) AddLog("TESO先行：每30对先等待CPU校正，再提交本对双眼检测；保留原图坐标，连续飞行期间暂存新参数。逐对处理所有帧并记录耗时，用于PC顺序模拟。");
        else if(onlineTeso) AddLog("在线 TESO 已开启：CPU 后台每30对尝试更新；连续球轨迹期间暂存新参数。此PC测试不代表RK实机60fps。");
        AddLog("处理结束后自动生成网页回放，可循环播放并调整倍速。");
        if(maskRelease) AddLog("离手像素证据来自同帧原图和运动Mask；仅保留8对回溯缓存。证据不足时明确显示旧框回退，不把回溯区间当作独立精度验收。");
    }
    void AddLog(string s) { log.AppendText(s + Environment.NewLine); }
    void OpenSample() {
        string pointer = Path.Combine(appDir, "verified-sample.txt");
        if(File.Exists(pointer)) OpenBrowser(File.ReadAllText(pointer, Encoding.UTF8).Trim());
        else AddLog("请先测试视频，完成后即可查看按新定义生成的样例。");
    }
    void Report(int percent, Update update) { if(worker.IsBusy) worker.ReportProgress(percent, update); }
    void LoadResult(string receipt) {
        var d = ReadJson(receipt);
        var job = new Job { Video = Convert.ToString(Get(d, "source_video")), Case = Path.GetDirectoryName(Path.GetFullPath(receipt)),
            Result = Convert.ToString(Get(d, "result")), Replay = Convert.ToString(Get(d, "replay")), Event = Get(d, "final_event"), Frames = (int)Long(Get(d, "processed")), Latest = Get(d, "latest_measurement") };
        video.Text = job.Video; Completed(this, new RunWorkerCompletedEventArgs(job, null, false));
    }
    public void RunBatch() {
        int start = Array.IndexOf(args, "--batch"); var receipts = new List<string>();
        if(start < 0 || start + 1 >= args.Length) throw new ArgumentException("--batch requires AVI paths");
        foreach(string path in args.Skip(start + 1)) {
            if(!File.Exists(path)) throw new FileNotFoundException("Video missing", path);
            var job = new Job { Video = Path.GetFullPath(path), Case = Path.Combine(root, "results", "pc", DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 6)) };
            var e = new DoWorkEventArgs(job); Work(this, e); receipts.Add(Path.Combine(job.Case, "app-run-receipt.json"));
            WriteJson(Path.Combine(appDir, "batch-receipt.json"), new { cases = receipts, complete = false });
        }
        WriteJson(Path.Combine(appDir, "batch-receipt.json"), new { cases = receipts, complete = true });
    }
    static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }
    static Dictionary<string, object> Obj(object value) { return value as Dictionary<string, object> ?? new Dictionary<string, object>(); }
    static object Get(object value, string key) { object found; return Obj(value).TryGetValue(key, out found) ? found : null; }
    static object[] Arr(object value) { return value as object[] ?? new object[0]; }
    static bool Bool(object value) { return value is bool && (bool)value; }
    static long Long(object value) { return Convert.ToInt64(value); }
    static string Hash(string file) { using(var input = File.OpenRead(file)) using(var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(input)).Replace("-", "").ToLowerInvariant(); }
    object ReadJson(string file) { return json.DeserializeObject(File.ReadAllText(file, Encoding.UTF8)); }
    void WriteJson(string file, object value) { File.WriteAllText(file, json.Serialize(value), Utf8); }
    void StartTest() {
        if(worker.IsBusy) return;
        try {
            string path = Path.GetFullPath(video.Text.Trim().Trim('"'));
            if(!File.Exists(path)) throw new Exception("视频不存在：" + path);
            if(!String.Equals(Path.GetExtension(path), ".avi", StringComparison.OrdinalIgnoreCase)) throw new Exception("当前原始导入器需要 MJPEG 编码的 AVI，不能将 MP4 仅改后缀使用。");
            if(new FileInfo(path).Length > 128L * 1024 * 1024) throw new Exception("视频超过当前导入器的 128 MiB 上限，请先截成较短的单次抛球片段。");
            if(!File.Exists(exe) || !File.Exists(config) || !File.Exists(calibration)) throw new Exception("缺少程序或配置文件，请保留整个项目目录。\r\n" + exe);
            var job = new Job { Video = path, Case = Path.Combine(root, "results", "pc", DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0, 6)) };
            cancelled = false; latestReplay = latestResult = null; run.Enabled = choose.Enabled = video.Enabled = replay.Enabled = folder.Enabled = false; stop.Enabled = true;
            height.Text = velocity.Text = chord.Text = "—"; resultTitle.Text = "本次测试结果"; progress.Style = ProgressBarStyle.Marquee;
            status.Text = "正在检查配置并导入视频…"; AddLog("开始：" + path); AddLog("输出：" + job.Case); worker.RunWorkerAsync(job);
        } catch(Exception ex) { MessageBox.Show(this, ex.Message, "无法开始测试", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    class Job { public string Video, Case, Replay, Result; public object Event, Latest; public int Frames; }
    class Update { public string Text; public int Done, Total; }
    void ValidateModels() {
        var m = ReadJson(config); foreach(var pair in Obj(Get(m, "models"))) {
            string path = Convert.ToString(Get(pair.Value, "path")); string expected = Convert.ToString(Get(pair.Value, "sha256"));
            if(!File.Exists(path) || Hash(path) != expected) throw new Exception("模型文件缺失或校验不符：" + path);
        }
        var manifest = ReadJson(Path.Combine(root, "config", "calibration-manifest.json"));
        if(Hash(calibration) != Convert.ToString(Get(manifest, "calibration_sha256"))) throw new Exception("当前标定文件校验不符。");
    }
    void Work(object sender, DoWorkEventArgs e) {
        var job = (Job)e.Argument; Directory.CreateDirectory(job.Case); ValidateModels();
        string manifest = Path.Combine(job.Case, "input", "manifest.json");
        Execute(job, "import", new string[] { "--import-video", job.Video, "--manifest", manifest }, null, 0);
        var input = ReadJson(manifest); job.Frames = Arr(Get(input, "frames")).Length;
        if(job.Frames == 0) throw new Exception("视频中没有可用帧。");
        job.Result = Path.Combine(job.Case, "result");
        Execute(job, "inference", new string[] { "--input", manifest, "--output", job.Result, "--detector", "model", "--model-config", config,
            "--measurement-calibration", calibration, "--detect-right", "--detector-timeout-ms", "30000", "--no-images", "--no-stages" }, Path.Combine(job.Result, "frames.jsonl"), job.Frames);
        var runInfo = ReadJson(Path.Combine(job.Result, "run.json"));
        if(Convert.ToString(Get(runInfo, "status")) != "passed" || Long(Get(runInfo, "errors")) != 0 || Long(Get(runInfo, "processed")) != job.Frames) throw new Exception("程序未完整处理视频，请查看本次日志。");
        Report(100, new Update { Text = "推理完成，正在生成本次视频回放…", Done = job.Frames, Total = job.Frames });
        var frameRows = File.ReadLines(Path.Combine(job.Result, "frames.jsonl"), Encoding.UTF8).Where(x => !String.IsNullOrWhiteSpace(x)).Select(x => json.DeserializeObject(x)).ToArray();
        if(frameRows.Length != job.Frames) throw new Exception("结果帧数与输入帧数不一致。");
        job.Event = Get(Get(frameRows[frameRows.Length - 1], "measurement"), "events");
        // Idle calibration changes start a new event window. Preserve the last
        // valid flight for the session summary, with its source calibration.
        foreach(var row in frameRows) {
            var ev = Get(Get(row, "measurement"), "events");
            if(Bool(Get(ev, "fit_valid"))) job.Event = ev;
        }
        job.Replay = MakeReplay(job, manifest, input, frameRows);
        WriteJson(Path.Combine(job.Case, "app-run-receipt.json"), new { source_video = job.Video, source_sha256 = Hash(job.Video), input_manifest_sha256 = Hash(manifest),
            executable_sha256 = Hash(exe), model_config_sha256 = Hash(config), calibration_sha256 = Hash(calibration), processed = job.Frames,
            run_status = "passed", online_teso = onlineTeso, teso_before_detection = sequentialTeso,
            mask_release_enabled = maskRelease,
            timing_scope = sequentialTeso ? "PC_causal_serial_simulation_all_source_frames_no_dropping" : "PC_offline_functional_test",
            result = job.Result, replay = job.Replay, final_event = job.Event,
            display_metrics = TossMetrics.FromEvent(job.Event), app_sha256 = Hash(Application.ExecutablePath), metric_definition = TossMetrics.Version });
        BuildWebReplay(job);
        var latestFile = Path.Combine(job.Case, "motion-current", "latest-release.json");
        if(File.Exists(latestFile)) job.Latest = ReadJson(latestFile);
        var savedReceipt = Obj(ReadJson(Path.Combine(job.Case, "app-run-receipt.json")));
        savedReceipt["latest_measurement"] = job.Latest;
        WriteJson(Path.Combine(job.Case, "app-run-receipt.json"), savedReceipt);
        if(!File.Exists(Path.Combine(appDir, "verified-sample.txt"))) File.WriteAllText(Path.Combine(appDir, "verified-sample.txt"), job.Replay, Utf8);
        e.Result = job;
    }
    void Execute(Job job, string stage, string[] arguments, string frames, int total) {
        if(cancelled) throw new OperationCanceledException();
        string console = Path.Combine(job.Case, stage + ".log");
        var info = new ProcessStartInfo(exe, String.Join(" ", arguments.Select(Quote))) { WorkingDirectory = root, UseShellExecute = false,
            CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        info.EnvironmentVariables["PIPELINE_B_DIAGNOSTIC_RELAX"] = "1";
        info.EnvironmentVariables["PIPELINE_TESO"] = onlineTeso ? "1" : "0";
        info.EnvironmentVariables["PIPELINE_MASK_RELEASE"] = maskRelease ? "1" : "0";
        if(sequentialTeso) info.EnvironmentVariables["PIPELINE_TESO_SYNC_EVAL"] = "1";
        else info.EnvironmentVariables.Remove("PIPELINE_TESO_SYNC_EVAL");
        info.EnvironmentVariables["PIPELINE_TESO_STRIDE"] = "30";
        var watch = Stopwatch.StartNew();
        using(var writer = new StreamWriter(console, false, Utf8)) using(var process = new Process { StartInfo = info }) {
            object gate = new object();
            process.OutputDataReceived += delegate(object s, DataReceivedEventArgs line) { if(line.Data != null) lock(gate) { writer.WriteLine(line.Data); writer.Flush(); } };
            process.ErrorDataReceived += delegate(object s, DataReceivedEventArgs line) { if(line.Data != null) lock(gate) { writer.WriteLine(line.Data); writer.Flush(); } };
            child = process; process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            int tick = 0;
            while(!process.WaitForExit(250)) {
                if(cancelled) { try { process.Kill(); } catch { } }
                if(++tick % 4 == 0 && total > 0) {
                    int done = CountFrames(frames); Report(Math.Min(99, done * 100 / total),
                        new Update { Text = "正在实际推理 " + done + " / " + total + " 对 · 已用 " + watch.Elapsed.ToString(@"mm\:ss"), Done = done, Total = total });
                }
            }
            process.WaitForExit(); child = null;
            WriteJson(Path.Combine(job.Case, stage + "-receipt.json"), new { arguments = arguments, exit_code = process.ExitCode, seconds = watch.Elapsed.TotalSeconds, log = console });
            if(cancelled) throw new OperationCanceledException();
            if(process.ExitCode != 0) {
                string detail = File.ReadAllText(console, Encoding.UTF8); if(detail.Length > 1800) detail = detail.Substring(detail.Length - 1800);
                throw new Exception((stage == "import" ? "视频导入失败；请检查是否为 2560×720 MJPEG AVI。" : "实际推理失败。") + "\r\n" + detail + "\r\n日志：" + console);
            }
        }
    }
    static int CountFrames(string file) {
        if(String.IsNullOrEmpty(file) || !File.Exists(file)) return 0;
        try { using(var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)) using(var reader = new StreamReader(stream, Encoding.UTF8)) {
            int n = 0; for(string line; (line = reader.ReadLine()) != null;) if(line.EndsWith("}")) ++n; return n; } } catch(IOException) { return 0; }
    }
    void Progress(object sender, ProgressChangedEventArgs e) {
        var u = (Update)e.UserState; progress.Style = ProgressBarStyle.Continuous; progress.Value = Math.Max(0, Math.Min(100, e.ProgressPercentage)); status.Text = u.Text;
    }
    void Completed(object sender, RunWorkerCompletedEventArgs e) {
        child = null; run.Enabled = choose.Enabled = video.Enabled = true; stop.Enabled = false; progress.Style = ProgressBarStyle.Continuous;
        if(e.Error != null) {
            status.Text = cancelled ? "测试已停止，已有日志保留。" : "测试失败，原因见下方。";
            AddLog(e.Error.Message); if(!cancelled) MessageBox.Show(this, e.Error.Message, "测试失败", MessageBoxButtons.OK, MessageBoxIcon.Error); return;
        }
        var job = (Job)e.Result; latestReplay = job.Replay; latestResult = job.Case; replay.Enabled = folder.Enabled = true; progress.Value = 100;
        var ev = job.Event;
        var metric = TossMetrics.FromEvent(ev);
        if(Bool(Get(metric, "valid"))) {
            height.Text = (Convert.ToDouble(Get(metric, "height_m")) * 100).ToString("F2") + " cm";
            velocity.Text = Convert.ToDouble(Get(ev, "launch_velocity_angle_from_vertical_deg")).ToString("F2") + "°";
            chord.Text = Convert.ToDouble(Get(metric, "angle_from_vertical_deg")).ToString("F2") + "°";
            status.Text = "测试完成：" + job.Frames + " 对；高度/角度已按离手点与最高点计算；" + (Get(ev, "contact") == null ? "触拍未确认。" : "触拍另行记录。");
            AddLog("高度 = 最高点Z − 离手点Z；抛球角度 = atan2(水平位移, 抛球高度)。触拍点不参与这两项计算。");
            if(job.Latest != null) {
                height.Text = Convert.ToDouble(Get(job.Latest, "height_cm")).ToString("F2") + " cm";
                chord.Text = Convert.ToDouble(Get(job.Latest, "angle_deg")).ToString("F2") + "°";
            }
            resultTitle.Text = job.Latest != null ? "本次测试结果 · 运动转折离手" : "本次测试结果";
            AddLog("初始事件方法：" + Convert.ToString(Get(ev, "release_estimator")) + "；最终测量见网页回放。");
        } else { height.Text = velocity.Text = chord.Text = "—"; status.Text = "测试完成：" + job.Frames + " 对，错误 0；尚无有效抛球拟合。"; }
        AddLog("事件状态：" + Convert.ToString(Get(ev, "reason"))); AddLog("结果：" + job.Case); AddLog("点击“查看本次回放”可检查刚测试的视频，不会打开旧样例。");
    }
    string MakeReplay(Job job, string manifest, object input, object[] frames) {
        return Path.Combine(job.Case, "replay", "index.html");
    }
    void BuildWebReplay(Job job) {
        string script = Path.Combine(root, "pc", Bool(Get(job.Event, "fit_valid")) ? "latest_release.py" : "replay.py");
        var info = new ProcessStartInfo("python", Quote(script) + " " + Quote(job.Case)) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        info.EnvironmentVariables["PYTHONUTF8"] = "1";
        using(var writer = new StreamWriter(Path.Combine(job.Case, "replay-build.log"), false, Utf8))
        using(var process = new Process { StartInfo = info }) {
            object gate = new object();
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs line) { if(line.Data != null) lock(gate) writer.WriteLine(line.Data); };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs line) { if(line.Data != null) lock(gate) writer.WriteLine(line.Data); };
            child=process; process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            process.WaitForExit(); child=null;
            if(cancelled) throw new OperationCanceledException();
            if(process.ExitCode != 0) throw new Exception("回放生成失败，原始结果已保存：" + job.Case);
        }
    }
    void OpenBrowser(string file) {
        try {
            if(String.IsNullOrEmpty(file) || !File.Exists(file)) throw new Exception("回放尚未生成，请先完成一次测试。\r\n" + file);
            string browser = BrowserPath();
            if(browser == null) throw new Exception("未找到 Edge 或 Chrome。可手动在现代浏览器打开：\r\n" + file);
            var started = Process.Start(new ProcessStartInfo(browser, Quote(new Uri(Path.GetFullPath(file)).AbsoluteUri)) { UseShellExecute = false });
            WriteJson(Path.Combine(appDir, "last-browser-launch.json"), new { browser = browser, file = file, process_id = started == null ? 0 : started.Id });
            AddLog("已在浏览器打开：" + file);
        } catch(Exception ex) { MessageBox.Show(this, ex.Message, "无法打开回放", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }
    static string BrowserPath() {
        foreach(string name in new string[] { "msedge.exe", "chrome.exe" }) {
            foreach(var hive in new RegistryKey[] { Registry.CurrentUser, Registry.LocalMachine }) {
                using(var key = hive.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\" + name)) {
                    if(key != null) { string candidate = Convert.ToString(key.GetValue(null)).Trim('"'); if(File.Exists(candidate)) return candidate; }
                }
            }
            foreach(var parent in new string[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) }) {
                string candidate = Path.Combine(parent, name == "msedge.exe" ? @"Microsoft\Edge\Application\msedge.exe" : @"Google\Chrome\Application\chrome.exe");
                if(File.Exists(candidate)) return candidate;
            }
        }
        return null;
    }
}

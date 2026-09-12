// Small .NET Framework launcher. Windows 10/11 include the required runtime.
// Embedded manifest is authoritative; cached binaries are SHA-256 verified.
using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Diagnostics;
using System.Collections.Generic;
using System.Threading;
using System.Windows.Forms;

class CacheLauncher {
    const string VersionId = "@VERSION_ID@";
    const string Marker = "QingyunClicker managed runtime v1";
    static string root;
    class Entry { public string Path, Hash; public long Size; }
    static string Hex(byte[] value) { return BitConverter.ToString(value).Replace("-", "").ToLowerInvariant(); }
    static string HashFile(string file) {
        using (var hash = new SHA256Cng()) using (var stream = File.OpenRead(file)) return Hex(hash.ComputeHash(stream));
    }
    static void CheckDirectory(string directory) {
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("缓存目录不能是链接：" + directory);
    }
    static string Inside(string directory, string relative) {
        string prefix = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string path = Path.GetFullPath(Path.Combine(prefix, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("非法缓存路径");
        return path;
    }
    static List<Entry> Manifest() {
        var entries = new List<Entry>();
        using (var reader = new StreamReader(Assembly.GetExecutingAssembly().GetManifestResourceStream("manifest"))) {
            string line;
            while ((line = reader.ReadLine()) != null) {
                var parts = line.Split('|');
                entries.Add(new Entry { Hash=parts[0], Size=long.Parse(parts[1]), Path=parts[2] });
            }
        }
        return entries;
    }
    static bool Validate(string directory, List<Entry> entries) {
        if (!Directory.Exists(directory)) return false;
        CheckDirectory(directory);
        foreach (string sub in Directory.GetDirectories(directory, "*", SearchOption.AllDirectories)) CheckDirectory(sub);
        var allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (Entry e in entries) {
            string path=Inside(directory,e.Path); allowed.Add(path);
            if (!File.Exists(path)) return false;
            var info=new FileInfo(path);
            if ((info.Attributes & FileAttributes.ReparsePoint)!=0 || info.Length!=e.Size || HashFile(path)!=e.Hash) return false;
        }
        allowed.Add(Path.Combine(directory,".managed")); allowed.Add(Path.Combine(directory,".inuse"));
        foreach (string path in Directory.GetFiles(directory,"*",SearchOption.AllDirectories)) if (!allowed.Contains(path)) return false;
        return true;
    }
    static FileStream Gate() {
        var watch=Stopwatch.StartNew();
        while (true) {
            try { return new FileStream(Path.Combine(root,".gate"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException) { if(watch.ElapsedMilliseconds>60000) throw; Thread.Sleep(75); }
        }
    }
    static bool DeleteManaged(string directory) {
        if (!Directory.Exists(directory)) return true;
        CheckDirectory(directory);
        string marker=Path.Combine(directory,".managed");
        if((!File.Exists(marker)||File.ReadAllText(marker)!=Marker) && Path.GetFileName(directory)!=VersionId) return false;
        foreach(string sub in Directory.GetDirectories(directory,"*",SearchOption.AllDirectories)) CheckDirectory(sub);
        try {
            using(var check=new FileStream(Path.Combine(directory,".inuse"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) {}
            Directory.Delete(directory,true); return true;
        } catch(IOException) { return false; } catch(UnauthorizedAccessException) { return false; }
    }
    static void Extract(string directory, List<Entry> entries) {
        string staging=Path.Combine(root,VersionId+".tmp."+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(staging); File.WriteAllText(Path.Combine(staging,".managed"),Marker);
        try {
            using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("payload"))
            using(var zip=new ZipArchive(stream,ZipArchiveMode.Read)) {
                foreach(var entry in zip.Entries) {
                    string path=Inside(staging,entry.FullName);
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    using(var input=entry.Open()) using(var output=File.Create(path)) input.CopyTo(output);
                }
            }
            if(!Validate(staging,entries)) throw new IOException("运行文件校验失败，请重新下载应用。");
            if(Directory.Exists(directory) && !DeleteManaged(directory)) throw new IOException("运行文件正在使用或缓存不完整，请关闭连点器后重试。");
            Directory.Move(staging,directory);
        } finally { if(Directory.Exists(staging)) DeleteManaged(staging); }
    }
    // Windows command line escaping, including quotes and trailing backslashes.
    static string Quote(string arg) {
        var result=new StringBuilder("\""); int slashes=0;
        foreach(char c in arg) {
            if(c=='\\') { slashes++; continue; }
            if(c=='"') { result.Append('\\',slashes*2+1); result.Append(c); slashes=0; continue; }
            result.Append('\\',slashes); slashes=0; result.Append(c);
        }
        result.Append('\\',slashes*2); return result.Append('"').ToString();
    }
    [STAThread] static int Main(string[] args) {
        try {
            bool test=args.Length==2 && args[0]=="--smoke-test";
            root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"QingyunClicker","runtime");
            if(test && !String.IsNullOrEmpty(Environment.GetEnvironmentVariable("QINGYUN_TEST_CACHE"))) root=Path.GetFullPath(Environment.GetEnvironmentVariable("QINGYUN_TEST_CACHE"));
            Directory.CreateDirectory(root); CheckDirectory(root);
            bool clear=args.Length==1&&args[0]=="--clear-cache";
            if(args.Length==2&&args[0]=="--clear-cache-after") {
                int pid;
                if(!Int32.TryParse(args[1],out pid)) throw new IOException("无效的清理请求");
                try { using(var previous=Process.GetProcessById(pid)) if(!previous.WaitForExit(20000)) throw new IOException("请先关闭连点器再清理缓存。"); }
                catch(ArgumentException) {}
                clear=true;
            }
            if(clear) {
                int remaining=0;
                using(Gate()) foreach(string dir in Directory.GetDirectories(root)) {
                    string name=Path.GetFileName(dir);
                    if(name.Length>=64 && System.Text.RegularExpressions.Regex.IsMatch(name,"^[0-9a-f]{64}(\\.tmp\\.[0-9a-f]{32})?$"))
                        if(!DeleteManaged(dir)) remaining++;
                }
                MessageBox.Show(remaining==0?"运行缓存已清理。下次启动将重新释放。":"已清理空闲缓存；正在运行的版本保留。请退出连点器后再次清理。","轻云连点器");
                return 0;
            }
            string version=Path.Combine(root,VersionId);
            FileStream lease;
            using(Gate()) {
                var entries=Manifest();
                if(!Validate(version,entries)) Extract(version,entries);
                lease=new FileStream(Path.Combine(version,".inuse"),FileMode.OpenOrCreate,FileAccess.Read,FileShare.Read);
                foreach(string old in Directory.GetDirectories(root)) if(old!=version && System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(old),"^[0-9a-f]{64}(\\.tmp\\.[0-9a-f]{32})?$")) DeleteManaged(old);
            }
            using(lease) {
                string arguments=String.Join(" ",Array.ConvertAll(args,Quote));
                var info=new ProcessStartInfo(Path.Combine(version,"QingyunRuntime.exe"),arguments);
                info.UseShellExecute=false; info.WorkingDirectory=version;
                info.EnvironmentVariables["QINGYUN_LAUNCHER_PATH"]=Assembly.GetExecutingAssembly().Location;
                info.EnvironmentVariables["QINGYUN_RUNTIME_CACHE"]=root;
                info.EnvironmentVariables["QINGYUN_WRAPPER_PID"]=Process.GetCurrentProcess().Id.ToString();
                using(var process=Process.Start(info)) { process.WaitForExit(); return process.ExitCode; }
            }
        } catch(Exception ex) { MessageBox.Show("启动失败："+ex.Message,"轻云连点器",MessageBoxButtons.OK,MessageBoxIcon.Error); return 1; }
    }
}

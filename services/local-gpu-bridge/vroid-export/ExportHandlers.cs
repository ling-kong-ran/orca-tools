using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Il2CppInterop.Runtime;
using UnityEngine;
using static VroidStudioMcp.Interop;
using static VroidStudioMcp.VroidState;

namespace VroidStudioMcp;

// Toolkit extension: use Studio's real exporter, never a desktop/file-dialog macro.
public static class ExportHandlers
{
    private static object _screen;
    public static void OnExportScreen(object __instance) => _screen = __instance;

    private static void RequiredSet(object target, string key, object value)
    {
        if (!Set(target, key, value)) throw new InvalidOperationException("VRM metadata field unavailable: " + key);
    }

    public static IEnumerator Export(CommandDispatcher.Context ctx)
    {
        string path = CommandUtil.Arg(ctx, 0), format = CommandUtil.Arg(ctx, 1) ?? "1.0";
        string title = CommandUtil.Arg(ctx, 2), author = CommandUtil.Arg(ctx, 3);
        bool replace = string.Equals(CommandUtil.Arg(ctx, 4), "true", StringComparison.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path) ||
            !string.Equals(Path.GetExtension(path), ".vrm", StringComparison.OrdinalIgnoreCase) ||
            (format != "1.0" && format != "0.0") || string.IsNullOrWhiteSpace(title) || string.IsNullOrWhiteSpace(author))
        { ctx.Error = "export_vrm requires absolute .vrm path, format 1.0|0.0, title and author"; yield break; }
        if (File.Exists(path) && !replace) { ctx.Error = "destination exists; replace=true required"; yield break; }
        if (!Directory.Exists(Path.GetDirectoryName(path))) { ctx.Error = "destination directory does not exist"; yield break; }
        if (!_modelReady || _modelUpdating) { ctx.Error = "model is not ready for export"; yield break; }

        string temporary = Path.Combine(Path.GetDirectoryName(path), ".export-" + Guid.NewGuid().ToString("N") + ".vrm");
        UnityEngine.Coroutine running = null;
        MonoBehaviour executor = null;
        bool entered = false, succeeded = false, failed = false;
        // Root callbacks for the entire native coroutine lifetime.
        var success = DelegateSupport.ConvertDelegate<Il2CppSystem.Action>(new Action(() => succeeded = true));
        var failure = DelegateSupport.ConvertDelegate<Il2CppSystem.Action>(new Action(() => failed = true));
        var progress = DelegateSupport.ConvertDelegate<Il2CppSystem.Action<double>>(new Action<double>(_ => { }));
        try
        {
            _screen = null;
            Invoke(_editRootVm, "EnterToVRMExport"); entered = true;
            yield return CommandUtil.WaitUntil(() => _screen != null, 20f);
            if (_screen == null) throw new InvalidOperationException("export screen did not activate");
            var photo = RealObj(Get(_screen, "ObsoleteLegacyPhotoBoothViewModel"));
            if (photo == null) throw new InvalidOperationException("export view model unavailable");
            yield return CommandUtil.WaitUntil(() => Get(photo, "PreviewAvatar") != null &&
                Get(photo, "UmaGameObject") != null && !(Get(photo, "_isBlockingUpdateExportPreview") is true), 60f);
            if (Get(photo, "PreviewAvatar") == null || Get(photo, "UmaGameObject") == null)
                throw new InvalidOperationException("export model did not initialize");
            var settings = Get(photo, "ExportSettings");
            var metadataType = FindType(format == "1.0" ? "UniVRM10.VRM10ObjectMeta" : "VRM.glTF_VRM_Meta");
            var metadata = Activator.CreateInstance(metadataType ?? throw new InvalidOperationException("VRM metadata type unavailable"));
            // Fresh metadata prevents saved local contact details from entering the artifact.
            if (format == "1.0")
            {
                RequiredSet(metadata, "Name", title); RequiredSet(metadata, "Version", "1.0");
                var authors = new Il2CppSystem.Collections.Generic.List<string>(); authors.Add(author);
                RequiredSet(metadata, "Authors", authors);
                RequiredSet(metadata, "ContactInformation", ""); RequiredSet(metadata, "CopyrightInformation", "");
                RequiredSet(metadata, "References", new Il2CppSystem.Collections.Generic.List<string>());
                RequiredSet(metadata, "ThirdPartyLicenses", ""); RequiredSet(metadata, "OtherLicenseUrl", "");
            }
            else
            {
                RequiredSet(metadata, "title", title); RequiredSet(metadata, "version", "1.0");
                RequiredSet(metadata, "author", author); RequiredSet(metadata, "contactInformation", "");
                RequiredSet(metadata, "reference", "");
            }
            executor = RewrapTo(Get(photo, "PhotoBoothCoroutineExecutor"), typeof(MonoBehaviour)) as MonoBehaviour;
            if (executor == null) throw new InvalidOperationException("export coroutine executor unavailable");
            var routine = Invoke(photo, format == "1.0" ? "ExportVRM1" : "ExportVRM0", temporary, metadata,
                Get(settings, "IsEnableHairCombination"), false, Get(settings, "CurrentMaterialReductionMode"),
                true, success, failure, progress) as Il2CppSystem.Collections.IEnumerator;
            if (routine == null) throw new InvalidOperationException("native VRM export routine unavailable");
            running = executor.StartCoroutine(routine);
            yield return CommandUtil.WaitUntil(() => succeeded || failed, 180f);
            if (!succeeded || failed) throw new InvalidOperationException(failed ? "native VRM export failed" : "native VRM export timed out");
            using (var file = File.OpenRead(temporary))
            using (var reader = new BinaryReader(file))
            {
                if (file.Length < 20 || reader.ReadUInt32() != 0x46546c67 || reader.ReadUInt32() != 2 || reader.ReadUInt32() != file.Length)
                    throw new InvalidOperationException("exporter produced an invalid VRM container");
            }
            File.Move(temporary, path, replace);
            ctx.Result = new Dictionary<string, object> { ["saved"] = true, ["format"] = format,
                ["bytes"] = new FileInfo(path).Length, ["path"] = WinePaths.ToHost(path) };
        }
        finally
        {
            if (running != null && executor != null && !succeeded) executor.StopCoroutine(running);
            if (entered && _screen != null) { try { Invoke(_screen, "PopScreen"); } catch (Exception e) { PluginLog.LogError("VRM return to editor: " + e.Message); } }
            if (File.Exists(temporary)) File.Delete(temporary);
            GC.KeepAlive(success); GC.KeepAlive(failure); GC.KeepAlive(progress);
        }
    }
}

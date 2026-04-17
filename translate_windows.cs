// translate_windows.cs — Windows built-in translation via WinRT
// Requires: Windows 11 24H2+ (Windows.AI.Translation namespace)
// Build:     dotnet publish -r win-x64 -o . translate_windows.csproj
//
// Protocol (matches translate_apple.swift):
//   stdin:  {"texts": ["..."], "source": "ko", "target": "zh-Hant"}
//   stdout: ["...translated..."]
//   On any error: returns the original texts unchanged.

using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;

// Windows.AI.Translation is available on Windows 11 24H2+ (build 26100+)
// The namespace may be accessed via the Windows App SDK or directly via WinRT.
// We use late binding via Type.GetType so the binary degrades gracefully on
// older Windows versions where the API does not exist.

class Program
{
    static async Task Main(string[] args)
    {
        var input = Console.In.ReadToEnd().Trim();

        List<string> texts;
        string source, target;
        try
        {
            using var doc = JsonDocument.Parse(input);
            var root = doc.RootElement;
            texts  = new List<string>();
            foreach (var item in root.GetProperty("texts").EnumerateArray())
                texts.Add(item.GetString() ?? "");
            source = root.GetProperty("source").GetString() ?? "ko";
            target = root.GetProperty("target").GetString() ?? "zh-Hant";
        }
        catch
        {
            Console.WriteLine("[]");
            return;
        }

        if (texts.Count == 0)
        {
            Console.WriteLine("[]");
            return;
        }

        var results = await TranslateAsync(texts, source, target);
        Console.WriteLine(JsonSerializer.Serialize(results));
    }

    static async Task<List<string>> TranslateAsync(
        List<string> texts, string source, string target)
    {
        try
        {
            // Dynamically resolve Windows.AI.Translation so the binary loads on
            // older Windows without crashing at startup.
            var engineType = Type.GetType(
                "Windows.AI.Translation.TextTranslator, Windows, " +
                "ContentType=WindowsRuntime");

            if (engineType == null)
            {
                // API not available on this Windows version — return originals
                return texts;
            }

            // TextTranslator.CreateAsync(sourceLanguage, targetLanguage)
            var createMethod = engineType.GetMethod("CreateAsync",
                new[] { typeof(string), typeof(string) });
            if (createMethod == null) return texts;

            dynamic translator = await (dynamic)createMethod.Invoke(
                null, new object[] { source, target })!;

            var results = new List<string>();
            foreach (var text in texts)
            {
                try
                {
                    string translated = await translator.TranslateAsync(text);
                    results.Add(translated ?? text);
                }
                catch
                {
                    results.Add(text);
                }
            }
            return results;
        }
        catch
        {
            return texts;
        }
    }
}

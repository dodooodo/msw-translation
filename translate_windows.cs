// translate_windows.cs — Windows built-in translation via WinRT
// Long-running daemon mode: reads JSON lines from stdin, writes JSON lines to stdout.
// Requires: Windows 11 24H2+ (Windows.AI.Translation namespace)
// Build:     dotnet publish -r win-x64 -o . translate_windows.csproj
//
// Usage:
//   translate_windows.exe ko zh-Hant
//   Then send JSON lines on stdin, one per line:
//     {"texts":["안녕하세요","감사합니다"]}
//   Each line produces one JSON array line on stdout:
//     ["你好","謝謝"]

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
        if (args.Length < 2)
        {
            Console.Error.WriteLine("Usage: translate_windows <source_lang> <target_lang>");
            Console.Error.WriteLine("  Then send JSON lines on stdin: {\"texts\":[\"...\"]}");
            return;
        }

        string source = args[0];  // e.g. "ko"
        string target = args[1];  // e.g. "zh-Hant"

        // Create the translator once and reuse it for all requests
        dynamic translator = null;
        try
        {
            var engineType = Type.GetType(
                "Windows.AI.Translation.TextTranslator, Windows, " +
                "ContentType=WindowsRuntime");

            if (engineType != null)
            {
                var createMethod = engineType.GetMethod("CreateAsync",
                    new[] { typeof(string), typeof(string) });
                if (createMethod != null)
                {
                    translator = await (dynamic)createMethod.Invoke(
                        null, new object[] { source, target });
                }
            }
        }
        catch
        {
            // API not available — translator stays null, we'll return originals
        }

        // Main daemon loop: read JSON lines, translate, write JSON lines
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            line = line.Trim();
            if (string.IsNullOrEmpty(line))
                continue;

            List<string> texts;
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                texts = new List<string>();
                foreach (var item in root.GetProperty("texts").EnumerateArray())
                    texts.Add(item.GetString() ?? "");
            }
            catch
            {
                Console.WriteLine("[]");
                Console.Out.Flush();
                continue;
            }

            if (texts.Count == 0)
            {
                Console.WriteLine("[]");
                Console.Out.Flush();
                continue;
            }

            List<string> results;
            if (translator != null)
            {
                results = new List<string>();
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
            }
            else
            {
                // No translator available — return originals
                results = texts;
            }

            Console.WriteLine(JsonSerializer.Serialize(results));
            Console.Out.Flush();
        }
    }
}

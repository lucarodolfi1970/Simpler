using System;
using System.Collections.Generic;
using System.Globalization;

namespace Simpler
{
    /// <summary>
    /// User interface language. Italian is the source language (the text written in the code); English comes
    /// from the table in L.En.cs. "testo" returns the text in the chosen language.
    /// </summary>
    public static partial class L
    {
        public static string Lang { get; private set; } = "it";

        public static void Init(string setting)
        {
            Lang = setting switch
            {
                "it" => "it",
                "en" => "en",
                _ => CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "it" ? "it" : "en",
            };
        }

        public static string T(string it)
        {
            if (Lang == "it" || string.IsNullOrEmpty(it)) return it;
            return En.TryGetValue(it, out var en) ? en : it;
        }

        public static string F(string it, params object?[] args) => string.Format(CultureInfo.CurrentCulture, T(it), args);
    }
}

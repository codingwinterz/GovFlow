// The citizen-side dictionaries. English is the source; the others need native-speaker review.
import en from "./en.json";
import hi from "./hi.json";
import mr from "./mr.json";
import kok from "./kok.json";

export const DICTS = { en, hi, mr, kok };
export const htmlLang = (lang) => (lang === "kok" ? "gom" : lang);   // Konkani's ISO 639-3 code

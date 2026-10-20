// Ссылка на Figma: только https и figma.com / www.figma.com, как memory.figma_ok; имя и тип файла - из адреса
// figma.com/<тип>/<ключ>/<имя>. Без DOM: его проверяет tests/test_figma_js.py под node.
const HOSTS = ["figma.com", "www.figma.com"];
const KINDS = { design: "макет", file: "макет", board: "доска FigJam", proto: "прототип", slides: "слайды", deck: "слайды",
  make: "Make" };

export function figmaHref(url) {
  try {
    const u = new URL(String(url || "").trim());
    const ok = u.protocol === "https:" && HOSTS.includes(u.host) && !u.username && !u.password &&
      u.pathname.replace(/\//g, "") !== "";
    return ok ? u.href : "";
  } catch { return ""; }
}

// { href, kind, name } или null; name - "" без сегмента имени и у неизвестного типа (форма адреса не известна)
export function figmaMeta(url) {
  const href = figmaHref(url);
  if (!href) return null;
  const [type, , slug] = new URL(href).pathname.split("/").filter(Boolean);
  let name = "";
  const known = Object.hasOwn(KINDS, type);
  if (slug && known) {
    try { name = decodeURIComponent(slug); } catch { name = slug; }   // кривая %-последовательность - имя как есть
    name = name.replace(/-/g, " ").replace(/\s+/g, " ").trim();
  }
  return { href, kind: known ? KINDS[type] : "файл", name };
}

export const figmaAbout = (f) => (f.name ? `${f.kind} «${f.name}»` : f.kind);

"""Static regressions: python3 -B -m unittest discover -s tests -v.

No server, browser, network, third-party packages or Git checkout history needed.
Rendering, focus visibility and pointer geometry belong to browser QA.
"""

import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
HOME = "index.html"
EVENT = "evento-18-novembre-2026.html"
ARCHIVE = "DRAWRUN-by-ESUBEERANTE.html"
PAGES = (HOME, EVENT, ARCHIVE)


def normalize(text):
    return " ".join(text.split())


class Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def find(self, tag):
        return [node for node in self.walk() if node.tag == tag]

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        def chunks(node):
            for child in node.children:
                if isinstance(child, str):
                    yield child
                elif child.tag not in {"script", "style"}:
                    yield " " if child.tag == "br" else ""
                    yield from chunks(child)
        return normalize("".join(chunks(self)))


class Document(HTMLParser):
    VOID = set("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.current = self.root
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


class EventSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {
            name: Document((ROOT / name).read_text(encoding="utf-8")).root
            for name in PAGES
        }
        cls.historical = json.loads(
            (ROOT / "tests/fixtures/archive_2023.json").read_text(encoding="utf-8")
        )

    def one(self, nodes):
        self.assertEqual(len(nodes), 1, "Expected exactly one matching element")
        return nodes[0]

    def local_path(self, page, reference):
        url = urlsplit(reference)
        self.assertFalse(url.scheme or url.netloc, reference)
        path = unquote(url.path)
        target = ROOT / path.lstrip("/") if path.startswith("/") else (ROOT / page).parent / path
        target = target.resolve()
        if not path:
            target = ROOT / page
        elif target.is_dir():
            target = target / HOME
        self.assertTrue(target.is_relative_to(ROOT), reference)
        self.assertTrue(target.is_file(), f"{page}: missing local destination {reference}")
        return target

    def link_to(self, scope, page, destination):
        links = []
        for link in scope.find("a"):
            href = link.attrs.get("href", "")
            url = urlsplit(href)
            if href and not (url.scheme or url.netloc):
                if self.local_path(page, href) == ROOT / destination:
                    links.append(link)
        return self.one(links)

    def home_sections(self):
        sections = self.pages[HOME].find("section")
        upcoming = self.one([s for s in sections if s.find("time")])
        archive = self.one([s for s in sections if "Evento passato" in s.text()])
        self.assertIsNot(upcoming, archive)
        return upcoming, archive

    def test_pages_are_direct_static_italian_documents(self):
        for name, doc in self.pages.items():
            with self.subTest(page=name):
                self.assertEqual(self.one(doc.find("html")).attrs.get("lang"), "it")
                self.one(doc.find("head"))
                self.one(doc.find("body"))
                self.one(doc.find("main"))
                self.assertTrue(self.one(doc.find("title")).text())
                self.assertFalse([m for m in doc.find("meta") if
                                  m.attrs.get("http-equiv", "").lower() == "refresh"])
                self.assertFalse(doc.find("base"), "Navigation must resolve from the local page")

    def test_upcoming_date_is_correct_in_heading_and_machine_readable(self):
        self.assertEqual(datetime.date(2026, 11, 18).weekday(), 2)  # Wednesday
        for name in (HOME, EVENT):
            with self.subTest(page=name):
                heading = self.one(self.pages[name].find("h1"))
                date = self.one(heading.find("time"))
                self.assertEqual(date.attrs.get("datetime"), "2026-11-18")
                self.assertEqual(date.text(), "Mercoledì 18 novembre 2026")
                self.assertIn("Prossimo evento", heading.text())

    def test_home_event_and_return_navigation(self):
        upcoming, _ = self.home_sections()
        self.assertTrue(self.link_to(upcoming, HOME, EVENT).text())
        back = self.link_to(self.one(self.pages[EVENT].find("main")), EVENT, HOME)
        self.assertIn("home", back.text().lower())
        self.assertNotIn("tabindex", back.attrs)

    def test_archive_is_reachable_from_home_and_has_return_navigation(self):
        _, archive = self.home_sections()
        link = self.link_to(archive, HOME, ARCHIVE)
        self.assertIn("2023", link.text())
        self.assertIn("evento passato", link.text().lower())
        self.link_to(self.one(self.pages[ARCHIVE].find("main")), ARCHIVE, HOME)

    def test_all_five_details_are_individually_pending(self):
        details = self.one(self.pages[EVENT].find("dl"))
        terms, values = details.find("dt"), details.find("dd")
        expected = {"Orario", "Punto di ritrovo", "Percorso e distanza",
                    "Quota di partecipazione", "Iscrizioni"}
        self.assertCountEqual([term.text() for term in terms], expected)
        self.assertEqual(len(values), 5)
        for term in terms:
            with self.subTest(field=term.text()):
                value = self.one(term.parent.find("dd"))
                self.assertEqual(value.text(), "Da confermare")

    def test_signup_uses_native_disabled_button_with_explanation(self):
        main = self.one(self.pages[EVENT].find("main"))
        button = self.one(main.find("button"))
        self.assertIn("iscrizion", button.text().lower())
        self.assertIn("disabled", button.attrs, "ARIA or styling alone does not disable signup")
        self.assertEqual(button.attrs.get("type"), "button")
        for attr in ("href", "form", "formaction", "tabindex"):
            self.assertNotIn(attr, button.attrs)
        ancestor = button.parent
        while ancestor is not None:
            self.assertNotIn(ancestor.tag, {"a", "form"})
            ancestor = ancestor.parent
        descriptions = button.attrs.get("aria-describedby", "").split()
        self.assertTrue(descriptions)
        for description in descriptions:
            note = self.one([n for n in main.walk() if n.attrs.get("id") == description])
            self.assertIn("non sono ancora attive", note.text())

    def test_upcoming_signup_has_no_navigation_or_submission_escape(self):
        main = self.one(self.pages[EVENT].find("main"))
        self.assertFalse(main.find("form"))
        self.assertFalse(main.find("input"))
        self.assertFalse(main.find("script"))
        for node in main.walk():
            self.assertFalse([key for key in node.attrs if key.startswith("on")], node.tag)
        for link in main.find("a"):
            self.assertEqual(self.local_path(EVENT, link.attrs.get("href", "")), ROOT / HOME)
        for name in (HOME, EVENT):
            self.assertNotIn(self.historical["registration_url"], (ROOT / name).read_text())

    def test_original_archive_content_is_preserved_on_home_and_archive(self):
        _, home_archive = self.home_sections()
        for name, scope in ((HOME, home_archive),
                            (ARCHIVE, self.one(self.pages[ARCHIVE].find("main")))):
            with self.subTest(page=name):
                self.assertEqual([p.text() for p in scope.find("p")],
                                 self.historical["paragraphs"])

    def test_archived_signup_is_preserved_and_explicitly_historical(self):
        doc = self.pages[ARCHIVE]
        self.assertEqual(self.one(doc.find("h1")).text(), "Evento passato")
        self.assertIn("2023", self.one(doc.find("title")).text())
        signup = self.one([a for a in doc.find("a")
                           if a.attrs.get("href") == self.historical["registration_url"]])
        self.assertIn("evento passato", signup.text().lower())

    def test_historical_facts_do_not_leak_into_upcoming_content(self):
        upcoming, _ = self.home_sections()
        for name, scope in ((HOME, upcoming),
                            (EVENT, self.one(self.pages[EVENT].find("main")))):
            with self.subTest(page=name):
                text = scope.text()
                for old_fact in ("2023", "15:30", "17:00", "10€", "Panettone",
                                 "disegno misterioso", "traccia GPS", "maglietta"):
                    self.assertNotIn(old_fact.casefold(), text.casefold())
                self.assertNotRegex(text, r"\b\d{1,2}:\d{2}\b|\d+\s*€|\d+\s*km\b")

    def test_local_links_assets_and_fragments_exist(self):
        for name, doc in self.pages.items():
            for node in doc.walk():
                for attr in ("href", "src", "xlink:href"):
                    ref = node.attrs.get(attr)
                    if ref is None:
                        continue
                    with self.subTest(page=name, tag=node.tag, reference=ref):
                        self.assertTrue(ref.strip(), "Empty links reload the current page")
                        url = urlsplit(ref)
                        if url.scheme or url.netloc:
                            continue  # Remote availability is outside an offline regression test.
                        target = self.local_path(name, ref)
                        if url.fragment:
                            destination = self.pages.get(target.name)
                            self.assertIsNotNone(destination)
                            self.one([n for n in destination.walk()
                                      if n.attrs.get("id") == unquote(url.fragment)])

    def test_detail_and_archive_canonicals_resolve_to_their_own_files(self):
        for name in (EVENT, ARCHIVE):
            with self.subTest(page=name):
                canonical = self.one([n for n in self.pages[name].find("link")
                                      if "canonical" in n.attrs.get("rel", "").split()])
                self.assertEqual(self.local_path(name, canonical.attrs["href"]), ROOT / name)


if __name__ == "__main__":
    unittest.main()

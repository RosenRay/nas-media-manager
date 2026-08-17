from __future__ import annotations

from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


def _pretty(root: Element) -> str:
    rough = tostring(root, encoding="utf-8", xml_declaration=True)
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def tvshow_nfo(*, title: str, plot: str = "", year: str = "", genres: list[str] | None = None) -> str:
    root = Element("tvshow")
    SubElement(root, "title").text = title
    if plot:
        SubElement(root, "plot").text = plot
    if year:
        SubElement(root, "year").text = str(year)
    for genre in genres or []:
        if genre.strip():
            SubElement(root, "genre").text = genre.strip()
    return _pretty(root)


def season_nfo(*, season: int, title: str) -> str:
    root = Element("season")
    SubElement(root, "title").text = title
    SubElement(root, "seasonnumber").text = str(season)
    return _pretty(root)


def episode_nfo(*, title: str, showtitle: str, season: int, episode: int, plot: str = "", aired: str = "") -> str:
    root = Element("episodedetails")
    SubElement(root, "title").text = title
    SubElement(root, "showtitle").text = showtitle
    SubElement(root, "season").text = str(season)
    SubElement(root, "episode").text = str(episode)
    if plot:
        SubElement(root, "plot").text = plot
    if aired:
        SubElement(root, "aired").text = aired
    return _pretty(root)

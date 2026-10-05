"""The logo builder's reading of icons and of whose website a link is (scripts/build_logos.py)."""
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location("build_logos", Path(__file__).parents[1] / "scripts" / "build_logos.py")
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)


def test_the_icons_a_page_links_best_first():
    page = """<html><head><link rel="icon" href="/favicon-32.png" sizes="32x32">
      <link rel="apple-touch-icon" sizes="180x180" href="/apple-icon.png"><link rel="mask-icon" href="/mask.svg">
      <link rel="icon" type="image/svg+xml" href="https://cdn.example.com/logo.svg"></head></html>"""
    got = [(url, fit) for _, _, url, fit in bl.icon_links(page, "https://www.example.com/")]
    assert got[:3] == [("https://www.example.com/apple-icon.png", "cover"), ("https://cdn.example.com/logo.svg", "contain"),
                       ("https://www.example.com/favicon-32.png", "contain")]
    assert got[-2:] == [("https://www.example.com/apple-touch-icon.png", "cover"), ("https://www.example.com/favicon.ico", "contain")]
    assert all("mask" not in url for url, _ in got)                    # a one-colour Safari mask is not a logo


def test_picture_sizes():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 180, 180) + b"\x00" * 20
    ico = b"\x00\x00\x01\x00\x02\x00" + bytes([16, 16]) + b"\x00" * 14 + bytes([0, 0]) + b"\x00" * 14   # 16px and 256px
    assert bl.image_size(png) == (180, 180) and bl.image_size(ico) == (256, 256) and bl.image_size(b"<svg/>") is None


def test_whose_website_a_link_is():
    assert bl.theirs("https://www.dickeys.com/promos") == "www.dickeys.com"
    assert bl.theirs("https://www.facebook.com/somebar") == "" and bl.theirs("https://dallas.culturemap.com/x") == ""
    assert bl.belongs("Dickey's Barbecue Pit", "www.dickeys.com", "")
    assert bl.belongs("B&B Theatres", "www.bbtheatres.com", "")
    assert bl.belongs("Texas Science & Natural History Museum", "sciencemuseum.utexas.edu",
                      "<title>Texas Science &amp; Natural History Museum</title>")
    assert not bl.belongs("Whataburger", "www.example.com", "<title>Home</title>")

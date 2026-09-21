#!/usr/bin/env python3
"""Turn the Convergence Index artifact file (from claude.ai) into the website's index.html.
Usage: python3 tools/build_site.py <artifact.html> index.html"""
import re, sys, html as H
src = open(sys.argv[1], encoding="utf-8").read()
# the artifact read may include the viewer's wrapper; keep only our page (from <title> on)
i = src.find("<title>")
if i < 0: sys.exit("no <title> found - not the Convergence Index file")
body = src[i:]
body = re.sub(r"\s*</body>\s*</html>\s*$", "", body)
body = re.sub(r"^<title>.*?</title>\s*", "", body, count=1, flags=re.S)
if "const DATA" not in body or "const BUILD" not in body: sys.exit("DATA/BUILD missing - refusing to build")
m = re.search(r'"asOf":\s*"([^"]+)"', body)
desc = "2026 U.S. midterms: prediction markets and polling, blended — the chance each party wins the House, Senate and key governor races. Updated every morning at 6 AM ET."
head = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>The Convergence Index</title>
<meta name="description" content="{H.escape(desc)}">
<link rel="canonical" href="https://convergence-index.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="The Convergence Index">
<meta property="og:title" content="The Convergence Index">
<meta property="og:description" content="{H.escape(desc)}">
<meta property="og:url" content="https://convergence-index.com/">
<meta property="og:image" content="https://convergence-index.com/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="The Convergence Index logo">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="The Convergence Index">
<meta name="twitter:description" content="{H.escape(desc)}">
<meta name="twitter:image" content="https://convergence-index.com/og-image.png">
<meta name="data-as-of" content="{m.group(1) if m else ''}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23fcfbf8'/%3E%3Crect x='4' y='14' width='24' height='4' fill='%239b3a2e'/%3E%3Crect x='16' y='14' width='12' height='4' fill='%232c4a7a'/%3E%3Crect x='15' y='8' width='2' height='16' fill='%2317171a'/%3E%3C/svg%3E">
</head>
<body>
"""
open(sys.argv[2], "w", encoding="utf-8").write(head + body.strip() + "\n</body>\n</html>\n")
print("built", sys.argv[2], len(head) + len(body), "bytes; asOf", m.group(1) if m else "?")

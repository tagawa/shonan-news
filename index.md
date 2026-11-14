---
layout: default
title: Shonan News
---

{% comment %}
Which posts: everything fetched within 24 hours of the newest post (the latest daily run), topped
up to the 40 newest when that run was quiet. Chosen by fetch date so a late batch still reaches
the homepage, then shown under source-date headings as before. Everything else is in /archive/.
{% endcomment %}
{% assign newest = site.posts.first.date | date: "%s" | plus: 0 %}
{% assign cutoff = newest | minus: 86400 %}
{% assign floor_post = site.posts[39] | default: site.posts.last %}
{% assign floor = floor_post.date | date: "%s" | plus: 0 %}
{% if floor < cutoff %}{% assign cutoff = floor %}{% endif %}
{% assign recent = "" | split: "" %}
{% for post in site.posts %}
  {% assign fetched = post.date | date: "%s" | plus: 0 %}
  {% if fetched < cutoff %}{% break %}{% endif %}
  {% assign recent = recent | push: post %}
{% endfor %}
<section class="latest-news" aria-labelledby="latest-news-heading">
<div class="section-head">
  <h2 id="latest-news-heading">Latest news</h2>
  <a href="{{ '/archive/' | relative_url }}">Archive</a>
</div>
<nav class="area-links" aria-label="News by area">
  <ul>
    {% for area in site.data.areas %}<li><a href="{{ '/areas/' | append: area.slug | append: '/' | relative_url }}">{{ area.name | escape }}</a></li>{% endfor %}
  </ul>
</nav>
{% comment %}
The saved area first: a bar and a block of that area's posts for each area, all hidden, then today's
list. The head include's rules show the saved area's bar and block and hide its posts in the list
below. See the frontend spec, "Areas", "Saved area", "Home page order".
{% endcomment %}{% assign area_blocks = "" %}
{% for area in site.data.areas %}{% assign area_recent = "" | split: "" %}{% for post in recent %}{% include post-area.html post=post %}{% if post_area and post_area.slug == area.slug %}{% assign area_recent = area_recent | push: post %}{% endif %}{% endfor %}
<div class="area-bar" data-area="{{ area.slug }}" hidden>
  {% if area_recent.size > 0 %}<p>Showing {{ area.name | escape }} first.</p>{% else %}<p>Nothing new from {{ area.name | escape }} in this update. <a href="{{ '/areas/' | append: area.slug | append: '/' | relative_url }}">All {{ area.name | escape }} news</a></p>{% endif %}
  <button type="button" class="area-forget">Show all Shonan</button>
</div>
{% if area_recent.size > 0 %}{% capture area_block %}<div class="area-first" data-area="{{ area.slug }}" hidden>
{% include news-days.html posts=area_recent datelines=false %}
<h3 class="elsewhere-label">Elsewhere in Shonan</h3>
</div>
{% endcapture %}{% assign area_blocks = area_blocks | append: area_block %}{% endif %}{% endfor %}
{{ area_blocks }}
{% include news-days.html posts=recent %}
<p><a href="{{ '/archive/' | relative_url }}">Older summaries</a></p>
</section>

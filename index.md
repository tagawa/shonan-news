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
<h2 id="latest-news-heading" class="section-head">Latest news</h2>
{% include area-pills.html label="News by area" %}
{% comment %}
The saved area first: a block of that area's posts for each area with any, or a quiet-day line for each
without, all hidden, then today's list. The head include's rules show the saved area's and hide its
posts in the list below. See the frontend spec, "Areas", "Saved area", "Home page order".
{% endcomment %}{% assign area_blocks = "" %}
{% for area in site.data.areas %}{% assign area_recent = "" | split: "" %}{% for post in recent %}{% include post-area.html post=post %}{% if post_area and post_area.slug == area.slug %}{% assign area_recent = area_recent | push: post %}{% endif %}{% endfor %}{% if area_recent.size == 0 %}
<div class="area-bar" data-area="{{ area.slug }}" hidden>
  <p>Nothing new from {{ area.name | escape }} in this update. <a href="{{ '/areas/' | append: area.slug | append: '/' | relative_url }}">All {{ area.name | escape }} news</a></p>
</div>{% endif %}
{% if area_recent.size > 0 %}{% capture area_block %}<div class="area-first" data-area="{{ area.slug }}" hidden>
{% include news-days.html posts=area_recent datelines=false %}
<h3 class="elsewhere-label">Elsewhere in Shonan</h3>
</div>
{% endcapture %}{% assign area_blocks = area_blocks | append: area_block %}{% endif %}{% endfor %}
{{ area_blocks }}
{% include news-days.html posts=recent %}
<p><a href="{{ '/archive/' | relative_url }}">Older summaries</a></p>
</section>

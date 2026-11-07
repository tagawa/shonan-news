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
{% include news-days.html posts=recent %}
<p><a href="{{ '/archive/' | relative_url }}">Older summaries</a></p>
</section>

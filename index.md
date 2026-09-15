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
{% assign day_groups = recent | group_by_exp: "post", "post.source_date | default: post.date | date: '%Y-%m-%d'" %}
{% assign day_groups = day_groups | sort: "name" | reverse %}
{% for day in day_groups %}
  <section class="day-group">
    {% assign sorted_items = day.items | sort: "source_date" | reverse %}
    <h2 class="day-heading"><time datetime="{{ day.name }}">{{ sorted_items.first.source_date | default: sorted_items.first.date | date: '%-d %B %Y' }}</time></h2>
    {% for post in sorted_items %}
      <article class="item">
        <h3 class="item-title"><a href="{{ post.url | relative_url }}">{{ post.title }}</a></h3>
        {% include japanese-title.html text=post.source_title url=post.source_url %}
        <p class="item-lede">{{ post.lede | default: post.excerpt | strip_html }}</p>
      </article>
    {% endfor %}
  </section>
{% endfor %}
<p><a href="{{ '/archive/' | relative_url }}">Older summaries</a></p>

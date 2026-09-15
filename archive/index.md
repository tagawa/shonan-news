---
layout: default
title: Archive
permalink: /archive/
---

<h1>Archive</h1>
{% comment %}Months come from the posts, not the stubs, so a missing stub shows up as a broken link the test suite catches, not a silently absent month.{% endcomment %}
{% assign months = site.posts | group_by_exp: "post", "post.source_date | default: post.date | date: '%Y-%m'" | sort: "name" | reverse %}
<ul class="archive-list">
  {% for month in months %}
  <li><a href="{{ '/archive/' | append: month.name | append: '/' | relative_url }}">{{ month.name | append: '-01' | date: '%B %Y' }}</a></li>
  {% endfor %}
</ul>

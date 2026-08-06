---
layout: default
title: Shonan News
---

{% assign day_groups = site.posts | group_by_exp: "post", "post.source_date | default: post.date | date: '%Y-%m-%d'" %}
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

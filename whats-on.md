---
layout: default
title: What's on
permalink: /whats-on/
# The page is events already; a panel of them beside it would repeat itself.
whats_on_panel: false
---
{% include whats-on-events.html %}
<h1>What's on</h1>
<p>Upcoming events. Details can change so please check the original article before you go.</p>
{% include area-pills.html label="Events by area" %}
{% assign this_month = whats_on_today | slice: 0, 7 %}
{% assign event_months = whats_on_events | group_by_exp: "post", "post.event_date | date: '%Y-%m'" | sort: "name" %}
{% assign last_month = this_month %}
{% if event_months.size > 0 %}{% assign last_month = event_months.last.name %}{% endif %}
{% assign month_start = this_month | append: "-01" | date: "%s" | plus: 0 %}
{% comment %}Three years is a bound, not a limit anyone should meet; the loop stops at the last event month. Each step adds 32 days and snaps back to the 1st.{% endcomment %}
{% for step in (0..36) %}
  {% assign month = month_start | date: "%Y-%m" %}
  {% if month > last_month %}{% break %}{% endif %}
  {% assign month_group = event_months | where: "name", month | first %}
  {% if month == this_month or month_group %}{% include calendar-month.html month_start=month_start events=month_group.items %}{% endif %}
  {% assign month_start = month_start | plus: 2764800 | date: "%Y-%m" | append: "-01" | date: "%s" | plus: 0 %}
{% endfor %}
{% if whats_on_events.size == 0 %}<p>No upcoming events.</p>{% endif %}
{% comment %}With an area saved, only its events show (see the frontend spec, "Areas", "What's on pages").{% endcomment %}{% if whats_on_events.size > 0 %}{% for area in site.data.areas %}{% assign area_has_events = false %}{% for area_post in whats_on_events %}{% if area_post.town and area.towns contains area_post.town %}{% assign area_has_events = true %}{% break %}{% endif %}{% endfor %}{% unless area_has_events %}
<p class="whats-on-area-none" data-area="{{ area.slug }}" hidden>No upcoming events in {{ area.name | escape }}.</p>{% endunless %}{% endfor %}{% endif %}

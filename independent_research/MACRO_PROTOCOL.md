# CPI forecast component: locked before inspecting nowcast history or scores

Written 2026-10-29. This is a separate component test added after the initial
TSA/weather/price screens; it does not change their models or windows.

Use the Cleveland Fed archived monthly headline CPI month-over-month nowcast
at the final available forecast date on or before target-month end. Require
that the archive identifies first-release actual values and outcome-release
date. Never use a nowcast dated on or after its actual release date.

Baseline: that public nowcast. Challenger: add mean baseline error over the
last 24 target months whose releases were already known at the forecast
origin; require 12 past releases. No coefficient or period selection.

Test January 2024 through September 2026, excluding any month with missing or
substitute actual data (especially October 2025 CPI). Score monthly absolute
error and bias; uncertainty by three-release circular-block bootstrap, 2,000
replicates, fixed seed 20261029. This is a small sample and forecast-only.
It does not establish executable market returns. Archived first-release
labels or exact vintage timing that cannot be verified cause rejection.

# Power BI model and DAX reference

The report has four pages (Overview, Earthquakes, Storms, Platform). Every number and almost every line of text is a DAX measure, so titles, subtitles and insights update themselves each time the data is refreshed.

## Contents

1. [Data model](#data-model)
2. [Calculated columns](#calculated-columns)
3. [Core measures](#core-measures)
4. [Dynamic text](#dynamic-text)
5. [Comparing the two sources](#comparing-the-two-sources)
6. [Insight lines](#insight-lines)
7. [Helper measures](#helper-measures)
8. [Lessons learned](#lessons-learned)

## Data model

| Table | Role |
|---|---|
| `Earthquakes` | USGS events, loaded from PostgreSQL |
| `StormEvents` | NOAA storm events, loaded from PostgreSQL |
| `DateTable` | Shared date dimension used by every page |

- Both fact tables relate many-to-one to `DateTable[Date]` through a **date-only** column (`event_date_only`, `begin_date_only`), never a timestamp.
- Cross-filter direction is single, from `DateTable` to the fact tables.
- The two sources are **not** joined to each other. There is no defensible geographic or temporal key between USGS and NOAA records, so the report compares patterns, not individual events.

## Calculated columns

### DateTable

```dax
Year = YEAR ( DateTable[Date] )

MonthName = FORMAT ( DateTable[Date], "MMM YYYY" )

MonthSort = YEAR ( DateTable[Date] ) * 100 + MONTH ( DateTable[Date] )

Month Num = MONTH(DateTable[Date])

Month Short = FORMAT(DateTable[Date], "mmm")
```

`MonthName` is sorted by `MonthSort`, and `Month Short` is sorted by `Month Num` (1 to 12). `Month Short` has no year, so it groups the same month across all years for the seasonality charts.

### Earthquakes

```dax
Region =
VAR p = Earthquakes[place]
VAR commas = LEN(p) - LEN(SUBSTITUTE(p, ",", ""))
VAR raw =
    IF(commas = 0, p,
        TRIM(MID(p, FIND("|", SUBSTITUTE(p, ",", "|", commas)) + 1, LEN(p))))
RETURN
    SWITCH(raw,
        "CA", "California", "NV", "Nevada", "AK", "Alaska", "HI", "Hawaii",
        "WA", "Washington", "OR", "Oregon", "ID", "Idaho", "MT", "Montana",
        "UT", "Utah", "OK", "Oklahoma", "TX", "Texas", "WY", "Wyoming",
        "NM", "New Mexico", "AZ", "Arizona",
        raw)
```

USGS writes the `place` field as free text such as `10 km NE of Town, Alaska`. `Region` takes the text after the last comma and expands US state codes, so `CA` and `California` become a single bar in the Top 10 chart.

## Core measures

### Earthquakes

```dax
Total Earthquakes = COUNTROWS ( Earthquakes )

Significant Earthquake Count =
CALCULATE(COUNTROWS(Earthquakes), Earthquakes[magnitude] >= 6) + 0

% Significant Earthquakes =
DIVIDE([Significant Earthquake Count], [Total Earthquakes], 0)

Avg Magnitude = AVERAGE ( Earthquakes[magnitude] )

Max Magnitude = MAX ( Earthquakes[magnitude] )

Avg Depth = AVERAGE ( Earthquakes[depth] )
```

The `+ 0` in `Significant Earthquake Count` makes a filtered selection with no M6+ events show `0` instead of blank.

### Storms

```dax
Total Storm Events = COUNTROWS ( StormEvents )

Total Deaths = SUM ( StormEvents[total_deaths] )

Total Injuries = SUM ( StormEvents[total_injuries] )

Total Property Damage = SUM ( StormEvents[damage_property_usd] )

Total Crop Damage = SUM ( StormEvents[damage_crops_usd] )

Severe Event Count =
CALCULATE ( COUNTROWS ( StormEvents ), StormEvents[total_deaths] > 0 || StormEvents[total_injuries] > 0 )

Most Common Event Type =
VAR RankedTypes =
    ADDCOLUMNS(
        VALUES(StormEvents[event_type]),
        "@Count", CALCULATE(COUNTROWS(StormEvents))
    )
VAR TopType =
    TOPN(1, RankedTypes, [@Count], DESC)
RETURN
    MAXX(TopType, StormEvents[event_type])

Property Damage Label =
"$" & FORMAT([Total Property Damage] / 1000000000, "0.00") & "B"
```

`Property Damage Label` is a text measure because Power BI's built-in "Billions" display unit prints `bn` and the label cannot be customised.

## Dynamic text

```dax
Overview Subtitle =
"Real USGS earthquake and NOAA storm event data — validated end-to-end pipeline"

Earthquake Subtitle =
"Magnitude, depth and geographic characteristics of " &
FORMAT(COUNTROWS(Earthquakes) / 1000000, "0.0") & "M real earthquakes, " &
YEAR(MIN(Earthquakes[event_date_only])) & " to " & YEAR(MAX(Earthquakes[event_date_only]))

Storm Subtitle =
"Event types, seasonality and impact across " &
FORMAT(COUNTROWS(StormEvents) / 1000, "0") & "K real storm events, " &
YEAR(MIN(StormEvents[begin_date_only])) & " to " & YEAR(MAX(StormEvents[begin_date_only]))

Earthquake Coverage =
"EARTHQUAKE DATA:  " & FORMAT(MIN(Earthquakes[event_date_only]), "mmm yyyy") &
" to " & FORMAT(MAX(Earthquakes[event_date_only]), "mmm yyyy")

Storm Coverage =
"STORM DATA:  " & FORMAT(MIN(StormEvents[begin_date_only]), "mmm yyyy") &
" to " & FORMAT(MAX(StormEvents[begin_date_only]), "mmm yyyy")

Data Freshness Note =
"Data through " & FORMAT(MAX(Earthquakes[event_date_only]), "d mmm yyyy") & " (earthquakes) and " &
FORMAT(MAX(StormEvents[begin_date_only]), "d mmm yyyy") & " (storms). The latest year is year-to-date and updates with each pipeline run."

pipeline = "DATA PIPELINE"
```

The coverage and freshness lines move forward automatically whenever the pipeline loads newer data. The year-to-date wording stops viewers reading the partial latest year as a decline.

## Comparing the two sources

Raw counts are not comparable (about 1.7M earthquakes against 693K storm events), so each source is indexed to its own 2016 value:

```dax
Earthquake Index =
DIVIDE(
    COUNTROWS(Earthquakes),
    CALCULATE(COUNTROWS(Earthquakes), ALL(DateTable), DateTable[Year] = 2016)
) * 100

Storm Index =
DIVIDE(
    COUNTROWS(StormEvents),
    CALCULATE(COUNTROWS(StormEvents), ALL(DateTable), DateTable[Year] = 2016)
) * 100
```

Seasonality is each month's share of the source's total events:

```dax
Earthquake Month Share =
DIVIDE(
    COUNTROWS(Earthquakes),
    CALCULATE(COUNTROWS(Earthquakes), REMOVEFILTERS(DateTable))
)

Storm Month Share =
DIVIDE(
    COUNTROWS(StormEvents),
    CALCULATE(COUNTROWS(StormEvents), REMOVEFILTERS(DateTable))
)
```

## Insight lines

Each insight ranks values with `ADDCOLUMNS` and `TOPN`, then builds a sentence, so the wording and the numbers follow the data.

### Earthquakes page

```dax
Insight Top Region =
VAR tbl =
    ADDCOLUMNS(
        VALUES(Earthquakes[Region]),
        "n", CALCULATE(COUNTROWS(Earthquakes))
    )
VAR topRow = TOPN(1, tbl, [n], DESC)
VAR region = MAXX(topRow, Earthquakes[Region])
VAR cnt = MAXX(topRow, [n])
RETURN
    region & " leads with " & FORMAT(DIVIDE(cnt, COUNTROWS(Earthquakes)), "0%") &
    " of all recorded events"

Insight Strongest =
VAR t = TOPN(1, Earthquakes, Earthquakes[magnitude], DESC)
RETURN
    "Strongest event: M" & FORMAT(MAXX(t, Earthquakes[magnitude]), "0.0") &
    ", " & MAXX(t, Earthquakes[place]) &
    " (" & YEAR(MAXX(t, Earthquakes[event_date_only])) & ")"

Insight Peak Year =
VAR tbl =
    ADDCOLUMNS(
        VALUES(DateTable[Year]),
        "n", CALCULATE([Significant Earthquake Count])
    )
VAR topRow = TOPN(1, tbl, [n], DESC)
RETURN
    "Peak M6+ year: " & MAXX(topRow, DateTable[Year]) &
    " with " & MAXX(topRow, [n]) & " significant earthquakes"
```

### Storms page

```dax
Insight Deadliest =
VAR tbl =
    ADDCOLUMNS(
        VALUES(StormEvents[event_type]),
        "d", [Total Deaths]
    )
VAR topRow = TOPN(1, tbl, [d], DESC)
RETURN
    MAXX(topRow, StormEvents[event_type]) & " is the deadliest event type, with " &
    FORMAT(MAXX(topRow, [d]), "#,0") & " deaths"

Insight Peak Injuries =
VAR tbl =
    ADDCOLUMNS(
        VALUES(DateTable[Year]),
        "i", [Total Injuries]
    )
VAR topRow = TOPN(1, tbl, [i], DESC)
RETURN
    "Injuries peaked in " & MAXX(topRow, DateTable[Year]) &
    " with " & FORMAT(MAXX(topRow, [i]), "#,0") & " recorded"

Insight Peak Month =
VAR tbl =
    ADDCOLUMNS(
        VALUES(DateTable[Month Short]),
        "n", CALCULATE(COUNTROWS(StormEvents))
    )
VAR topRow = TOPN(1, tbl, [n], DESC)
RETURN
    "Storm activity peaks in " & MAXX(topRow, DateTable[Month Short]) &
    " (" & FORMAT(MAXX(topRow, [n]), "#,0") & " events across the period)"
```

### Platform page (both sources)

```dax
Insight Combined Quakes =
VAR tbl = ADDCOLUMNS(VALUES(DateTable[Year]), "i", [Earthquake Index])
VAR topRow = TOPN(1, tbl, [i], DESC)
RETURN
    "Earthquake activity peaked in " & MAXX(topRow, DateTable[Year]) &
    " (" & FORMAT(MAXX(topRow, [i]) - 100, "+0;-0") & "% vs 2016)"

Insight Combined Storms =
VAR tbl = ADDCOLUMNS(VALUES(DateTable[Year]), "i", [Storm Index])
VAR topRow = TOPN(1, tbl, [i], DESC)
RETURN
    "Storm activity peaked in " & MAXX(topRow, DateTable[Year]) &
    " (" & FORMAT(MAXX(topRow, [i]) - 100, "+0;-0") & "% vs 2016)"

Insight Seasonality =
VAR tbl =
    ADDCOLUMNS(
        VALUES(DateTable[Month Short]),
        "s", [Storm Month Share],
        "q", [Earthquake Month Share]
    )
VAR stormTop = TOPN(1, tbl, [s], DESC)
RETURN
    "Storms peak in " & MAXX(stormTop, DateTable[Month Short]) &
    " (" & FORMAT(MAXX(stormTop, [s]), "0%") & " of events); earthquakes stay between " &
    FORMAT(MINX(tbl, [q]), "0%") & " and " & FORMAT(MAXX(tbl, [q]), "0%") & " every month"
```

## Helper measures

These come from earlier versions of the Overview coverage strip. The current report uses the `Coverage` measures above, so these may now be unused and can be removed when tidying the model.

```dax
Max Month Name =
VAR MaxSort = MAX ( DateTable[MonthSort] )
RETURN
LOOKUPVALUE ( DateTable[MonthName], DateTable[MonthSort], MaxSort )

Min Month Name =
VAR MinSort = MIN ( DateTable[MonthSort] )
RETURN
LOOKUPVALUE ( DateTable[MonthName], DateTable[MonthSort], MinSort )

EQ Max Month =
VAR MaxDate = MAX ( Earthquakes[time] )
RETURN FORMAT ( MaxDate, "MMM YYYY" )

EQ Min Month =
VAR MinDate = MIN ( Earthquakes[time] )
RETURN FORMAT ( MinDate, "MMM YYYY" )

Storm Max Month =
VAR MaxDate = MAX ( StormEvents[begin_timestamp] )
RETURN FORMAT ( MaxDate, "MMM YYYY" )

Storm Min Month =
VAR MinDate = MIN ( StormEvents[begin_timestamp] )
RETURN FORMAT ( MinDate, "MMM YYYY" )
```

## Lessons learned

**1. A timestamp is a bad join key.** The storm relationship originally used `begin_date_time`. It only matched `DateTable[Date]` when the time was exactly midnight, so about 80% of deaths and 98% of injuries fell into a blank month row. A diagnostic table with totals turned on exposed it. Switching the relationship to `begin_date_only` made the monthly totals reconcile with the yearly total.

**2. `ALL` on one column can leave the rest of the filter in place.** The first seasonality measure used `ALL(DateTable[Month Short])` and every month showed 100%. `REMOVEFILTERS(DateTable)` clears the whole date context.

**3. Aggregates inside `ADDCOLUMNS` need `CALCULATE`.** An early `Insight Peak Month` returned the total storm count for every month, because the count was not wrapped in `CALCULATE`. The chart showed June as the peak while the text said September, which is how it was caught.

**4. Check generated text against the visual beside it.** Every insight line was compared with its chart before publishing.

**5. DAX gotcha.** A variable called `top` is rejected as a reserved word, so ranked rows are stored in `topRow`.

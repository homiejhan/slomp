# Blind judge for regular deals

Used by the regular-deals verification (`slomp verify --plan regulars`) for two tests. The judge is a separate model
run that sees only the packet, never Slomp's code, registry or labels.

Prompt (identical every run; only the two paths change). It was amended once, after run 1, which had shown the judge
one passage of one page and list entries without the day their page is for: the two sentences about a list page's
title and about passages from more than one page were added.

> You are checking a deals app. Read the JSON file at PACKET. It has `industries` (a fixed list, each with an id,
> name and description) and `items`. Each item has a `qid` and a `kind`, and you answer by kind.
>
> `kind: "industry"`: the item has an offer `title` and the `store` or venue making it. List each industry from the
> fixed list whose shoppers would reasonably expect to find this offer there. Several can apply; list all that
> clearly do, and none that are a stretch. Judge from the title and store only.
>
> `kind: "summary"`: the item has a `card` (the place, the offer as the app words it, when it runs, an end date if
> any, and conditions) and `source_text` (a passage from the page the app cites; it is lowercased and may include
> text about other offers or other places before and after the relevant part). When a passage begins with a list
> page's title in square brackets, the entry comes from that page, and a page of deals for one weekday gives its
> entries that day. The text can hold passages from more than one page the app cites, separated by "‖ [another page
> the app cites]"; the card may draw on all of them together. Decide whether the card is faithful
> to the source text. Answer `faithful: false` if the card states a day, time, price, discount or condition that
> the source text contradicts or does not support, or if it leaves out a condition that changes who can get the
> deal or when: membership required, app or online only, dine-in only, an age limit, a time window, an end date.
> Leaving out minor detail is fine, and so is rewording. When false, say what is wrong in `problem`, in one short
> sentence.
>
> Read no other file. Write JSON to LABELS in exactly this form, covering every item:
> `{"labels": [{"qid": "...", "industries": ["id", ...]}, {"qid": "...", "faithful": true, "problem": ""}]}`.
> Then reply with one line saying how many items you labeled.

An industry item passes when the industry Slomp showed the deal under is among the judge's industries. A summary item
passes when the judge answers `faithful: true`.

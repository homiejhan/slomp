# Blind industry judge

Used by each verification iteration for the industry tests (L-IND, O-IND). The judge is a separate model run that
sees only an item's title and store, never Slomp's labels, rules or categories.

Prompt (identical every iteration; only the two paths change):

> You are labeling products for a shopping app. Read the JSON file at PACKET. It has `industries` (a fixed list,
> each with an id, name and description) and `items` (each with a `qid`, a product or offer `title`, and the
> `store` selling it). For every item, list each industry from the fixed list whose shoppers would reasonably
> expect to find this product or offer there. Several industries can apply; list all that clearly do, and none
> that are a stretch. Judge from the title and store only, and read no other file. Write JSON to LABELS in exactly
> this form, covering every item: `{"labels": [{"qid": "...", "industries": ["id", ...]}]}`. Then reply with one
> line saying how many items you labeled.

A test passes when the industry Slomp showed the item under is among the judge's industries.

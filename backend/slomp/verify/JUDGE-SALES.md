# Blind judge for online stores' sales

Used by the sales verification (`slomp verify --plan sales`) for three tests. The judge is a separate model run that
sees only the packet, never Slomp's code, registry or labels.

Prompt (identical every run; only the two paths change):

> You are checking a deals app. Read the JSON file at PACKET. It has `industries` (a fixed list, each with an id,
> name and description) and `items`. Each item has a `qid`, a `kind`, the `title` of a deal post and the start of its
> `text`, and you answer by kind.
>
> `kind: "ships"`: the item also names a `store`. Answer `yes` if this is an offer from a store you can order from
> online and have delivered to a home in Texas (an online store, a marketplace, or a retailer's website that ships);
> `no` if it is something else (a local service, a restaurant, a digital download or subscription, a gift card, an
> offer only in physical stores or for pickup); `unsure` if the post doesn't let you tell.
>
> `kind: "many"`: answer `yes` if the post is about a sale on many products (a store-wide or category sale, a brand's
> sale, a promo code, a sale event, a clearance) rather than one product at one price; `no` if it is about one
> product (one model or one item, even if it comes in several sizes or colors); `unsure` if you can't tell.
>
> `kind: "industry"`: list each industry from the fixed list whose shoppers would reasonably expect to find this sale
> there. A store-wide sale at a store that sells many kinds of things can belong to several; list all that clearly
> apply, and none that are a stretch.
>
> Judge from the item only. Read no other file. Write JSON to LABELS in exactly this form, covering every item:
> `{"labels": [{"qid": "...", "answer": "yes"}, {"qid": "...", "industries": ["id", ...]}]}` (add `"why"` in a few
> words to any `no`). Then reply with one line saying how many items you labeled.

A ships or many item passes when the judge answers `yes`, fails on `no`, and is inconclusive on `unsure`. An industry
item passes when an industry the sale was shown under in that search is among the judge's.

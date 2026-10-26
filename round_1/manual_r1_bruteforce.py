"""
stanford x berkeley manual round 1 — brute force go brrr
==============================================
ok so basically we got 2 products in this auction thing:
  DRYLAND FLAX  — buyback 30/unit, no fees lol free money
  EMBER MUSHROOM — buyback 20/unit, 0.10/unit fee (rip)

we submit LAST so we get worst time priority (pain)
clearing price = whatever maximizes volume, ties go to higher price

the play: find the exact vol where 1 more unit would push CP up by 1
then bid exactly 1 below that. ez clap

result: FLAX buy 9999 @ 30 = 9,999 profit
        MUSH buy 19999 @ 17 = 77,996 profit
        total ~88k manual XIRECs lets gooo
"""


def get_cp(bids, asks, lo=1, hi=60):
    """find clearing price — max volume wins, ties = higher price"""
    best_vol, best_px = 0, 0
    for px in range(lo, hi):
        buy_side = sum(v for p, v in bids if p >= px)
        sell_side = sum(v for p, v in asks if p <= px)
        matched = min(buy_side, sell_side)
        if matched > best_vol or (matched == best_vol and px > best_px):
            best_vol, best_px = matched, px
    return best_px, best_vol


def sim_buy(our_px, our_sz, book_bids, book_asks):
    """simulate our buy order — we get filled LAST (worst priority sadge)"""
    all_bids = book_bids + [(our_px, our_sz)]
    cp, total = get_cp(all_bids, book_asks)
    if our_px < cp:
        return cp, 0  # bid too low, no fill rip
    left = total
    our_fill = 0
    # higher bids fill first, we're last at our level
    for lvl in sorted(set(p for p, _ in all_bids), reverse=True):
        if lvl < cp or left <= 0:
            break
        others = sum(v for p, v in book_bids if p == lvl)
        others_fill = min(others, left); left -= others_fill
        us = our_sz if our_px == lvl else 0
        us_fill = min(us, left); left -= us_fill; our_fill += us_fill
    return cp, our_fill


def sim_sell(our_px, our_sz, book_bids, book_asks):
    """simulate our sell order — same deal, last priority"""
    all_asks = book_asks + [(our_px, our_sz)]
    cp, total = get_cp(book_bids, all_asks)
    if our_px > cp:
        return cp, 0  # ask too high, nobody wants it
    left = total
    our_fill = 0
    # lower asks fill first
    for lvl in sorted(set(p for p, _ in all_asks)):
        if lvl > cp or left <= 0:
            break
        others = sum(v for p, v in book_asks if p == lvl)
        others_fill = min(others, left); left -= others_fill
        us = our_sz if our_px == lvl else 0
        us_fill = min(us, left); left -= us_fill; our_fill += us_fill
    return cp, our_fill


def yolo_sweep(name, bids, asks, buyback, fee, max_px=50, max_sz=60000):
    """try literally every combo and find the bag"""
    net = buyback - fee
    print(f"\n{'='*70}")
    print(f"  {name}  |  buyback={buyback}  fee={fee}  net={net}")
    print(f"{'='*70}")

    cp0, tv0 = get_cp(bids, asks)
    print(f"  baseline (no us): CP={cp0}, traded={tv0:,}")

    goat = (0, "", 0, 0, 0, 0)  # (profit, dir, px, sz, cp, fill)

    for side in ["BUY", "SELL"]:
        side_best = (0, "", 0, 0, 0, 0)

        for px in range(1, max_px + 1):
            # coarse scan first — step by 500 to find where CP changes
            tipping = []
            prev_cp = None
            for sz in range(1, max_sz + 1, 500):
                if side == "BUY":
                    cp, fl = sim_buy(px, sz, bids, asks)
                    bag = fl * (net - cp) if fl > 0 and cp < net else 0
                else:
                    cp, fl = sim_sell(px, sz, bids, asks)
                    bag = fl * (cp - net) if fl > 0 and cp > net else 0
                if prev_cp is not None and cp != prev_cp:
                    tipping.append(sz)
                prev_cp = cp

            # fine scan — unit precision around tipping points (this is where the money is)
            px_best = (0, 0, 0, 0)

            check_szs = set()
            for tp in tipping:
                for v in range(max(1, tp - 600), min(max_sz + 1, tp + 600)):
                    check_szs.add(v)
            for v in range(1, max_sz + 1, 500):
                check_szs.add(v)

            for sz in check_szs:
                if side == "BUY":
                    cp, fl = sim_buy(px, sz, bids, asks)
                    bag = fl * (net - cp) if fl > 0 and cp < net else 0
                else:
                    cp, fl = sim_sell(px, sz, bids, asks)
                    bag = fl * (cp - net) if fl > 0 and cp > net else 0

                if bag > px_best[0]:
                    px_best = (bag, sz, cp, fl)

            bag, sz, cp, fl = px_best
            if bag > side_best[0]:
                side_best = (bag, side, px, sz, cp, fl)

        if side_best[0] > 0:
            pr, d, p, v, c, f = side_best
            print(f"\n  best {side}: {d} {v:,} @ {p}  |  CP={c} fill={f:,} profit={pr:,.1f}")
        else:
            print(f"\n  best {side}: nah nothing profitable")

        if side_best[0] > goat[0]:
            goat = side_best

    # leaderboard of top 30 plays
    print(f"\n  --- top 30 plays ---")
    all_plays = []

    for side in ["BUY", "SELL"]:
        for px in range(1, max_px + 1):
            tipping = []
            prev_cp = None
            for sz in range(1, max_sz + 1, 500):
                if side == "BUY":
                    cp, fl = sim_buy(px, sz, bids, asks)
                else:
                    cp, fl = sim_sell(px, sz, bids, asks)
                if prev_cp is not None and cp != prev_cp:
                    tipping.append(sz)
                prev_cp = cp

            for tp in tipping:
                for sz in [tp - 1, tp, tp + 1]:
                    if sz < 1:
                        continue
                    if side == "BUY":
                        cp, fl = sim_buy(px, sz, bids, asks)
                        bag = fl * (net - cp) if fl > 0 and cp < net else 0
                    else:
                        cp, fl = sim_sell(px, sz, bids, asks)
                        bag = fl * (cp - net) if fl > 0 and cp > net else 0
                    if bag > 0:
                        all_plays.append((bag, side, px, sz, cp, fl))

    all_plays.sort(reverse=True)
    seen = set()
    cnt = 0
    for bag, d, p, v, c, f in all_plays:
        key = (d, p, c)
        if key in seen:
            continue
        seen.add(key)
        print(f"    {d:>4} {v:>7,} @ {p:>3}: CP={c:>3}, fill={f:>7,}, profit={bag:>12,.1f}")
        cnt += 1
        if cnt >= 30:
            break

    # the answer
    pr, d, p, v, c, f = goat
    print(f"\n  >>> GOAT PLAY: {d} {v:,} @ {p}")
    print(f"      CP={c}, fill={f:,}, profit={pr:,.1f}")

    # sanity check — vol +-5 around optimal to make sure we aint trippin
    print(f"\n  sanity check (vol +/-5):")
    for dv in range(-5, 6):
        v2 = v + dv
        if v2 < 1:
            continue
        if d == "BUY":
            c2, f2 = sim_buy(p, v2, bids, asks)
            p2 = f2 * (net - c2) if f2 > 0 and c2 < net else 0
        else:
            c2, f2 = sim_sell(p, v2, bids, asks)
            p2 = f2 * (c2 - net) if f2 > 0 and c2 > net else 0
        tag = " <<< THIS ONE" if dv == 0 else ""
        print(f"    {d} {v2:>7,} @ {p}: CP={c2}, fill={f2:>7,}, profit={p2:>12,.1f}{tag}")

    return goat


# ============================================
# the books (copied from the game)
# ============================================
# flax — ez money, buyback 30, no fees
flax_bids = [(30, 30000), (29, 5000), (28, 12000), (27, 28000)]
flax_asks = [(28, 40000), (31, 20000), (32, 20000), (33, 30000)]

# mushroom — buyback 20, fee 0.10/unit (annoying but still profitable)
mush_bids = [(20, 43000), (19, 17000), (18, 6000), (17, 5000),
             (16, 10000), (15, 5000), (14, 10000), (13, 7000)]
mush_asks = [(12, 20000), (13, 25000), (14, 35000), (15, 6000),
             (16, 5000), (18, 10000), (19, 12000)]

print("stanford x berkeley MANUAL R1 — brute force every single combo")
print("prices 1-50 x volumes 1-60k x buy+sell = millions of checks")
print("we will find the bag\n")

flax_goat = yolo_sweep("DRYLAND FLAX", flax_bids, flax_asks, buyback=30, fee=0, max_px=40, max_sz=60000)
mush_goat = yolo_sweep("EMBER MUSHROOM", mush_bids, mush_asks, buyback=20, fee=0.10, max_px=30, max_sz=60000)

print(f"\n{'='*70}")
print(f"  FINAL ANSWER (dont change this bro)")
print(f"{'='*70}")
fp, fd, fpr, fv, fcp, ff = flax_goat
mp, md, mpr, mv, mcp, mf = mush_goat
print(f"\n  DRYLAND FLAX:   {fd} {fv:,} @ {fpr}")
print(f"    CP={fcp}, fill={ff:,}, profit={fp:,.1f}")
print(f"\n  EMBER MUSHROOM: {md} {mv:,} @ {mpr}")
print(f"    CP={mcp}, fill={mf:,}, profit={mp:,.1f}")
print(f"\n  TOTAL BAG: {fp + mp:,.1f} XIRECs")
print(f"  we are so winning this round")
"""
Round 1 Manual Challenge - EXHAUSTIVE Brute Force Analysis
===========================================================
Products: DRYLAND FLAX (buyback=30, no fees), EMBER MUSHROOM (buyback=20, fee=0.10/unit)
We can BUY or SELL one order per product. We submit LAST (worst time priority).

Clearing price: maximizes traded volume; ties broken by HIGHER price.
"""

def find_clearing_price(all_bids, all_asks, lo=1, hi=60):
    best_traded, best_price = 0, 0
    for P in range(lo, hi):
        bv = sum(v for p, v in all_bids if p >= P)
        sv = sum(v for p, v in all_asks if p <= P)
        t = min(bv, sv)
        if t > best_traded or (t == best_traded and P > best_price):
            best_traded, best_price = t, P
    return best_price, best_traded


def fill_buy(our_price, our_vol, bids, asks):
    all_bids = bids + [(our_price, our_vol)]
    cp, traded = find_clearing_price(all_bids, asks)
    if our_price < cp:
        return cp, 0
    remaining = traded
    our_fill = 0
    for plevel in sorted(set(p for p, _ in all_bids), reverse=True):
        if plevel < cp or remaining <= 0:
            break
        existing = sum(v for p, v in bids if p == plevel)
        ours = our_vol if our_price == plevel else 0
        ef = min(existing, remaining); remaining -= ef
        of = min(ours, remaining); remaining -= of; our_fill += of
    return cp, our_fill


def fill_sell(our_price, our_vol, bids, asks):
    all_asks = asks + [(our_price, our_vol)]
    cp, traded = find_clearing_price(bids, all_asks)
    if our_price > cp:
        return cp, 0
    remaining = traded
    our_fill = 0
    for plevel in sorted(set(p for p, _ in all_asks)):
        if plevel > cp or remaining <= 0:
            break
        existing = sum(v for p, v in asks if p == plevel)
        ours = our_vol if our_price == plevel else 0
        ef = min(existing, remaining); remaining -= ef
        of = min(ours, remaining); remaining -= of; our_fill += of
    return cp, our_fill


def sweep_product(name, bids, asks, buyback, fee, max_price=50, max_vol=60000):
    net = buyback - fee
    print(f"\n{'='*70}")
    print(f"  {name}  |  Buyback={buyback}  Fee={fee}  Net={net}")
    print(f"{'='*70}")

    cp0, tv0 = find_clearing_price(bids, asks)
    print(f"  No-order baseline: CP={cp0}, traded={tv0:,}")

    best = (0, "", 0, 0, 0, 0)  # (profit, dir, price, vol, cp, fill)

    for direction in ["BUY", "SELL"]:
        dir_best = (0, "", 0, 0, 0, 0)
        
        for price in range(1, max_price + 1):
            # --- COARSE pass: step=500 to find tipping points ---
            tipping_vols = []
            last_cp = None
            for vol in range(1, max_vol + 1, 500):
                if direction == "BUY":
                    cp, fl = fill_buy(price, vol, bids, asks)
                    profit = fl * (net - cp) if fl > 0 and cp < net else 0
                else:
                    cp, fl = fill_sell(price, vol, bids, asks)
                    profit = fl * (cp - net) if fl > 0 and cp > net else 0
                if last_cp is not None and cp != last_cp:
                    tipping_vols.append(vol)
                last_cp = cp

            # --- FINE pass: unit precision near each tipping point ---
            price_best = (0, 0, 0, 0)  # (profit, vol, cp, fill)
            
            scan_vols = set()
            for tv in tipping_vols:
                for v in range(max(1, tv - 600), min(max_vol + 1, tv + 600)):
                    scan_vols.add(v)
            # Also add coarse grid
            for v in range(1, max_vol + 1, 500):
                scan_vols.add(v)

            for vol in scan_vols:
                if direction == "BUY":
                    cp, fl = fill_buy(price, vol, bids, asks)
                    profit = fl * (net - cp) if fl > 0 and cp < net else 0
                else:
                    cp, fl = fill_sell(price, vol, bids, asks)
                    profit = fl * (cp - net) if fl > 0 and cp > net else 0

                if profit > price_best[0]:
                    price_best = (profit, vol, cp, fl)

            profit, vol, cp, fl = price_best
            if profit > dir_best[0]:
                dir_best = (profit, direction, price, vol, cp, fl)

        # Print direction results
        if dir_best[0] > 0:
            pr, d, p, v, c, f = dir_best
            print(f"\n  Best {direction}: {d} {v:,} @ {p}  |  CP={c} fill={f:,} profit={pr:,.1f}")
        else:
            print(f"\n  Best {direction}: NO PROFITABLE ORDERS")

        if dir_best[0] > best[0]:
            best = dir_best

    # Print ALL top candidates across both directions
    print(f"\n  --- Top 30 orders (unit-precision scan) ---")
    all_results = []
    
    for direction in ["BUY", "SELL"]:
        for price in range(1, max_price + 1):
            # Find tipping points
            tipping_vols = []
            last_cp = None
            for vol in range(1, max_vol + 1, 500):
                if direction == "BUY":
                    cp, fl = fill_buy(price, vol, bids, asks)
                else:
                    cp, fl = fill_sell(price, vol, bids, asks)
                if last_cp is not None and cp != last_cp:
                    tipping_vols.append(vol)
                last_cp = cp

            # Check just before each tipping point
            for tv in tipping_vols:
                for vol in [tv - 1, tv, tv + 1]:
                    if vol < 1:
                        continue
                    if direction == "BUY":
                        cp, fl = fill_buy(price, vol, bids, asks)
                        profit = fl * (net - cp) if fl > 0 and cp < net else 0
                    else:
                        cp, fl = fill_sell(price, vol, bids, asks)
                        profit = fl * (cp - net) if fl > 0 and cp > net else 0
                    if profit > 0:
                        all_results.append((profit, direction, price, vol, cp, fl))

    all_results.sort(reverse=True)
    seen = set()
    count = 0
    for profit, d, p, v, c, f in all_results:
        key = (d, p, c)  # dedupe by direction+price+cp
        if key in seen:
            continue
        seen.add(key)
        print(f"    {d:>4} {v:>7,} @ {p:>3}: CP={c:>3}, fill={f:>7,}, profit={profit:>12,.1f}")
        count += 1
        if count >= 30:
            break

    # Verify optimal
    pr, d, p, v, c, f = best
    print(f"\n  >>> OPTIMAL: {d} {v:,} @ {p}")
    print(f"      CP={c}, fill={f:,}, profit={pr:,.1f}")

    print(f"\n  Verification (vol ±5 around optimal):")
    for dv in range(-5, 6):
        v2 = v + dv
        if v2 < 1: continue
        if d == "BUY":
            c2, f2 = fill_buy(p, v2, bids, asks)
            p2 = f2 * (net - c2) if f2 > 0 and c2 < net else 0
        else:
            c2, f2 = fill_sell(p, v2, bids, asks)
            p2 = f2 * (c2 - net) if f2 > 0 and c2 > net else 0
        tag = " <<<" if dv == 0 else ""
        print(f"    {d} {v2:>7,} @ {p}: CP={c2}, fill={f2:>7,}, profit={p2:>12,.1f}{tag}")

    return best


# ============================================
# ORDER BOOKS
# ============================================
FLAX_BIDS = [(30, 30000), (29, 5000), (28, 12000), (27, 28000)]
FLAX_ASKS = [(28, 40000), (31, 20000), (32, 20000), (33, 30000)]

MUSH_BIDS = [(20, 43000), (19, 17000), (18, 6000), (17, 5000),
             (16, 10000), (15, 5000), (14, 10000), (13, 7000)]
MUSH_ASKS = [(12, 20000), (13, 25000), (14, 35000), (15, 6000),
             (16, 5000), (18, 10000), (19, 12000)]

print("ROUND 1 MANUAL — EXHAUSTIVE BRUTE FORCE")
print("Prices: 1-50 | Volumes: 1-60,000 | Directions: BUY + SELL")
print("Unit precision at every tipping point")

fb = sweep_product("DRYLAND FLAX", FLAX_BIDS, FLAX_ASKS, buyback=30, fee=0, max_price=40, max_vol=60000)
mb = sweep_product("EMBER MUSHROOM", MUSH_BIDS, MUSH_ASKS, buyback=20, fee=0.10, max_price=30, max_vol=60000)

print(f"\n{'='*70}")
print(f"  FINAL ANSWER")
print(f"{'='*70}")
fp, fd, fpr, fv, fcp, ff = fb
mp, md, mpr, mv, mcp, mf = mb
print(f"\n  DRYLAND FLAX:   {fd} {fv:,} @ {fpr}")
print(f"    CP={fcp}, fill={ff:,}, profit={fp:,.1f}")
print(f"\n  EMBER MUSHROOM: {md} {mv:,} @ {mpr}")
print(f"    CP={mcp}, fill={mf:,}, profit={mp:,.1f}")
print(f"\n  TOTAL: {fp + mp:,.1f} XIRECs")
"""
Round 1 Manual Challenge — EXHAUSTIVE brute-force optimizer.
Checks every (direction, price, volume) combo for both products.
"""

# ===================== ORDER BOOKS =====================
# DRYLAND FLAX — buyback at 30/unit, no fees
FLAX_BIDS = [(30, 30_000), (29, 5_000), (28, 12_000), (27, 28_000)]
FLAX_ASKS = [(28, 40_000), (31, 20_000), (32, 20_000), (33, 30_000)]
FLAX_BUYBACK = 30
FLAX_BUY_FEE = 0
FLAX_SELL_FEE = 0

# EMBER MUSHROOM — buyback at 20/unit, fees 0.05 buy + 0.05 sell
MUSH_BIDS = [(20, 43_000), (19, 17_000), (18, 6_000), (17, 5_000),
             (16, 10_000), (15, 5_000), (14, 10_000), (13, 7_000)]
MUSH_ASKS = [(12, 20_000), (13, 25_000), (14, 35_000), (15, 6_000),
             (16, 5_000), (18, 10_000), (19, 12_000)]
MUSH_BUYBACK = 20
MUSH_BUY_FEE = 0.05   # fee per unit when buying
MUSH_SELL_FEE = 0.05   # fee per unit when selling


def find_clearing_price(all_bids, all_asks):
    """Find clearing price that maximizes traded volume. Ties → higher price."""
    best_traded = 0
    best_price = 0
    # Scan all possible prices
    all_prices = sorted(set(p for p, _ in all_bids + all_asks))
    for P in all_prices:
        bv = sum(v for p, v in all_bids if p >= P)
        sv = sum(v for p, v in all_asks if p <= P)
        t = min(bv, sv)
        if t > best_traded or (t == best_traded and P > best_price):
            best_traded = t
            best_price = P
    return best_price, best_traded


def compute_buy_fill(our_price, our_vol, existing_bids, existing_asks):
    """Compute fill for our BUY order. We have LAST time priority."""
    all_bids = existing_bids + [(our_price, our_vol)]
    cp, total_traded = find_clearing_price(all_bids, existing_asks)
    
    if our_price < cp:
        return cp, 0  # our bid below clearing → no fill
    
    remaining = total_traded
    our_fill = 0
    
    # All bid price levels, descending
    all_bid_prices = sorted(set(p for p, _ in all_bids), reverse=True)
    
    for price_level in all_bid_prices:
        if price_level < cp or remaining <= 0:
            break
        # Existing orders at this level (fill first — time priority)
        existing_vol = sum(v for p, v in existing_bids if p == price_level)
        existing_fill = min(existing_vol, remaining)
        remaining -= existing_fill
        # Our order at this level (fill last)
        our_vol_here = our_vol if our_price == price_level else 0
        our_fill_here = min(our_vol_here, remaining)
        remaining -= our_fill_here
        our_fill += our_fill_here
    
    return cp, our_fill


def compute_sell_fill(our_price, our_vol, existing_bids, existing_asks):
    """Compute fill for our SELL order. We have LAST time priority."""
    all_asks = existing_asks + [(our_price, our_vol)]
    cp, total_traded = find_clearing_price(existing_bids, all_asks)
    
    if our_price > cp:
        return cp, 0  # our ask above clearing → no fill
    
    remaining = total_traded
    our_fill = 0
    
    # All ask price levels, ascending (lowest ask fills first)
    all_ask_prices = sorted(set(p for p, _ in all_asks))
    
    for price_level in all_ask_prices:
        if price_level > cp or remaining <= 0:
            break
        # Existing orders at this level (fill first — time priority)
        existing_vol = sum(v for p, v in existing_asks if p == price_level)
        existing_fill = min(existing_vol, remaining)
        remaining -= existing_fill
        # Our order at this level (fill last)
        our_vol_here = our_vol if our_price == price_level else 0
        our_fill_here = min(our_vol_here, remaining)
        remaining -= our_fill_here
        our_fill += our_fill_here
    
    return cp, our_fill


def sweep_product(name, bids, asks, buyback, buy_fee, sell_fee, max_vol=100_001):
    """Brute-force ALL directions, prices, volumes for a product."""
    all_prices = sorted(set(p for p, _ in bids + asks))
    price_min = min(all_prices) - 3
    price_max = max(all_prices) + 3
    
    best_profit = 0
    best_order = None
    
    # Track tipping points for detailed output
    results = []
    
    # ========== BUY SIDE ==========
    # If we BUY: pay clearing_price, get units, sell at buyback
    # profit/unit = buyback - clearing_price - buy_fee - sell_fee(if buyback has fee)
    # For Flax: buyback sells at 30 with no fees → net = 30 - CP
    # For Mushroom: buyback at 20, but do fees apply to buyback?
    #   Conservative: fees on both auction buy AND buyback sell → net = 20 - CP - 0.10
    #   Optimistic: fees only on auction → net = 20 - CP - 0.05
    # We use conservative (0.10 total)
    
    for price in range(price_min, price_max + 1):
        last_cp = None
        last_fill = None
        for vol in range(1, max_vol):
            cp, fill = compute_buy_fill(price, vol, bids, asks)
            net_per_unit = buyback - cp - buy_fee - sell_fee
            profit = fill * net_per_unit
            
            if profit > best_profit:
                best_profit = profit
                best_order = ("BUY", price, vol, cp, fill, net_per_unit, profit)
            
            # Record tipping points (CP changes or fill stops growing)
            if cp != last_cp or (fill != last_fill and vol <= 5) or vol == max_vol - 1:
                if fill > 0 and net_per_unit > 0:
                    results.append(("BUY", price, vol, cp, fill, net_per_unit, profit))
                last_cp = cp
                last_fill = fill
    
    # ========== SELL SIDE ==========
    # If we SELL: deliver units at clearing_price
    # We don't initially own any units. 
    # Interpretation 1: We short sell → receive CP, must buy back at buyback → profit = CP - buyback - fees (negative)
    # Interpretation 2: We sell units we acquire... but this is one order, we can't buy and sell
    # Interpretation 3: The auction is a matching mechanism; selling means we provide at our price, receive CP
    #   Then we'd need to deliver goods we don't have... unless the game handles this
    # 
    # Let's check all interpretations:
    # If sell profit = CP - buyback - fees → profit when CP > buyback (unlikely given books)
    
    for price in range(price_min, price_max + 1):
        last_cp = None
        for vol in range(1, max_vol):
            cp, fill = compute_sell_fill(price, vol, bids, asks)
            # Interpretation: we sell at CP, receive CP per unit, no obligation to buy back
            # This would mean profit = CP * fill - fees(if any)... but this is "free money" which doesn't make sense
            # More realistic: sell at CP, must source goods at buyback price
            # profit/unit = CP - buyback + sell_fee... wait that's backwards
            # If we SELL in auction: we deliver goods and receive CP per unit
            # If goods cost us buyback price to source: profit = CP - buyback - fees
            # For Flax: CP - 30 - 0 (CP ~28, so this is -2, negative)
            # For Mushroom: CP - 20 - 0.10 (CP ~16, so -4.10, negative)
            
            net_per_unit = cp - buyback - buy_fee - sell_fee  
            profit = fill * net_per_unit
            
            if profit > best_profit:
                best_profit = profit
                best_order = ("SELL", price, vol, cp, fill, net_per_unit, profit)
            
            if cp != last_cp:
                if fill > 0:
                    results.append(("SELL", price, vol, cp, fill, net_per_unit, profit))
                last_cp = cp
    
    return best_profit, best_order, results


def detailed_sweep(name, bids, asks, buyback, buy_fee, sell_fee):
    """Unit-precision sweep around all critical tipping points."""
    all_prices = sorted(set(p for p, _ in bids + asks))
    price_min = min(all_prices) - 2
    price_max = max(all_prices) + 2
    
    print(f"\n{'='*70}")
    print(f" {name} — EXHAUSTIVE ANALYSIS")
    print(f"{'='*70}")
    print(f" Buyback: {buyback}, Buy fee: {buy_fee}, Sell fee: {sell_fee}")
    print(f" Net value (buy): buyback - CP - {buy_fee + sell_fee}")
    print(f" Bids: {bids}")
    print(f" Asks: {asks}")
    
    # Step 1: Find clearing without us
    cp0, tv0 = find_clearing_price(bids, asks)
    print(f"\n Without us: CP={cp0}, Traded={tv0:,}")
    
    # Step 2: Show clearing table without us
    print(f"\n Clearing table (no us):")
    for P in sorted(set(p for p, _ in bids + asks)):
        bv = sum(v for p, v in bids if p >= P)
        sv = sum(v for p, v in asks if p <= P)
        t = min(bv, sv)
        marker = " ← CLEARING" if P == cp0 else ""
        print(f"   P={P:>3}: Buy={bv:>8,}  Sell={sv:>8,}  Traded={t:>8,}{marker}")
    
    # Step 3: BUY sweep — find all tipping points with unit precision
    print(f"\n BUY ORDERS — Tipping point analysis:")
    
    buy_global_best = (0, None)
    
    for price in range(price_min, price_max + 1):
        tipping_points = []
        prev_cp = None
        prev_fill = None
        max_v = 80_001  # more than enough
        
        for vol in range(1, max_v):
            cp, fill = compute_buy_fill(price, vol, bids, asks)
            net = buyback - cp - buy_fee - sell_fee
            profit = fill * net
            
            if profit > buy_global_best[0]:
                buy_global_best = (profit, ("BUY", price, vol, cp, fill, net))
            
            if cp != prev_cp:
                if prev_cp is not None:
                    # Record last vol before CP change
                    tipping_points.append(("BEFORE", vol - 1, prev_cp, prev_fill,
                                          prev_fill * (buyback - prev_cp - buy_fee - sell_fee)))
                    tipping_points.append(("AFTER", vol, cp, fill,
                                          fill * (buyback - cp - buy_fee - sell_fee)))
                prev_cp = cp
            prev_fill = fill
        
        if tipping_points:
            has_profit = any(p[4] > 0 for p in tipping_points)
            if has_profit:
                print(f"\n   Price={price}:")
                for label, vol, cp, fill, profit in tipping_points:
                    if profit > 0 or label == "AFTER":
                        print(f"     {label:>6} vol={vol:>6,}: CP={cp}, fill={fill:>6,}, "
                              f"profit={profit:>12,.1f}"
                              f"{'  ← LOCAL PEAK' if label == 'BEFORE' and profit > 0 else ''}")
    
    # Step 4: SELL sweep
    print(f"\n SELL ORDERS — Analysis:")
    sell_global_best = (0, None)
    
    for price in range(price_min, price_max + 1):
        for vol in [1, 1000, 10000, 50000]:
            cp, fill = compute_sell_fill(price, vol, bids, asks)
            net = cp - buyback - buy_fee - sell_fee
            profit = fill * net
            if profit > sell_global_best[0]:
                sell_global_best = (profit, ("SELL", price, vol, cp, fill, net))
            if fill > 0 and profit > 0:
                print(f"   SELL {vol:>6,} @ {price}: CP={cp}, fill={fill:>6,}, profit={profit:>12,.1f}")
    
    if sell_global_best[1] is None or sell_global_best[0] <= 0:
        print("   No profitable SELL orders exist (all CPs below buyback + fees)")
    
    # Step 5: Global optimum
    if buy_global_best[0] >= sell_global_best[0]:
        best = buy_global_best
    else:
        best = sell_global_best
    
    d, p, v, cp, f, net = best[1]
    print(f"\n {'*'*50}")
    print(f" GLOBAL OPTIMUM: {d} {v:,} @ {p}")
    print(f"   CP={cp}, Fill={f:,}, Net/unit={net:.2f}, Profit={best[0]:,.1f}")
    print(f" {'*'*50}")
    
    return best


def verify_order(direction, price, vol, bids, asks, buyback, buy_fee, sell_fee):
    """Step-by-step verification of a specific order."""
    print(f"\n--- Verification: {direction} {vol:,} @ {price} ---")
    
    if direction == "BUY":
        all_bids = bids + [(price, vol)]
        all_asks = asks
    else:
        all_bids = bids
        all_asks = asks + [(price, vol)]
    
    print("Clearing price candidates:")
    all_p = sorted(set(p for p, _ in all_bids + all_asks))
    for P in all_p:
        bv = sum(v for p, v in all_bids if p >= P)
        sv = sum(v for p, v in all_asks if p <= P)
        t = min(bv, sv)
        print(f"  P={P:>3}: Buy={bv:>8,}  Sell={sv:>8,}  Traded={t:>8,}")
    
    cp, total = find_clearing_price(all_bids, all_asks)
    print(f"Clearing price: {cp}, Total traded: {total:,}")
    
    if direction == "BUY":
        _, fill = compute_buy_fill(price, vol, bids, asks)
        net = buyback - cp - buy_fee - sell_fee
    else:
        _, fill = compute_sell_fill(price, vol, bids, asks)
        net = cp - buyback - buy_fee - sell_fee
    
    print(f"Our fill: {fill:,}")
    print(f"Net/unit: {net:.2f}")
    print(f"Total profit: {fill * net:,.1f}")


if __name__ == "__main__":
    print("=" * 70)
    print(" ROUND 1 MANUAL CHALLENGE — EXHAUSTIVE BRUTE FORCE")
    print(" Checking ALL directions × ALL prices × ALL volumes")
    print("=" * 70)
    
    flax_best = detailed_sweep("DRYLAND FLAX", FLAX_BIDS, FLAX_ASKS,
                                FLAX_BUYBACK, FLAX_BUY_FEE, FLAX_SELL_FEE)
    
    mush_best = detailed_sweep("EMBER MUSHROOM", MUSH_BIDS, MUSH_ASKS,
                                MUSH_BUYBACK, MUSH_BUY_FEE, MUSH_SELL_FEE)
    
    # Verify the optima
    fd = flax_best[1]
    verify_order(fd[0], fd[1], fd[2], FLAX_BIDS, FLAX_ASKS,
                 FLAX_BUYBACK, FLAX_BUY_FEE, FLAX_SELL_FEE)
    
    md = mush_best[1]
    verify_order(md[0], md[1], md[2], MUSH_BIDS, MUSH_ASKS,
                 MUSH_BUYBACK, MUSH_BUY_FEE, MUSH_SELL_FEE)
    
    print(f"\n{'='*70}")
    print(f" FINAL ANSWER")
    print(f"{'='*70}")
    print(f" DRYLAND FLAX:   {fd[0]} {fd[2]:,} @ {fd[1]}  →  {flax_best[0]:,.1f} XIRECs")
    print(f" EMBER MUSHROOM: {md[0]} {md[2]:,} @ {md[1]}  →  {mush_best[0]:,.1f} XIRECs")
    print(f" COMBINED:       {flax_best[0] + mush_best[0]:,.1f} XIRECs")
    print(f"{'='*70}")
    
    # Also check: what if fees DON'T apply to buyback (optimistic scenario)?
    print(f"\n SENSITIVITY: What if mushroom fee is only 0.05 (buy side only)?")
    mush_opt = detailed_sweep("EMBER MUSHROOM (optimistic fees)", MUSH_BIDS, MUSH_ASKS,
                               MUSH_BUYBACK, 0.05, 0.0)

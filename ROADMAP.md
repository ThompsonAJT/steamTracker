# Roadmap

Running backlog, roughly in priority order. Update this file as items land or
priorities shift — treat it as the source of truth over anything said in chat.

## Do first

- [x] Confirm the genre dropdown works on the live site after a worker pass
- [ ] Tests and CI
  - [ ] pytest tests for price-change detection (`record_price` in ingest.py)
  - [ ] GitHub Actions workflow that runs the test suite on every push
- [ ] Smart polling: a priority queue that checks popular or recently-changed
      games more often, staying under ~200 requests/5min. `apps.poll_priority`
      and `apps.last_polled_at` already exist in the schema for this — they're
      just unused so far.
- [ ] Sales vs. player counts: chart player counts before/after discounts,
      show the average effect

## Next

- [ ] "Good deal?" badge comparing current price to historical low
- [ ] Public stats page from `poll_log` (uptime, success rate, response
      times, changes detected)
- [ ] Sign in through Steam (OpenID)
  - [ ] Verify each login response with Steam server-side
  - [ ] Signed-cookie session holding the SteamID
  - [ ] `users` table
- [ ] Import owned games and playtime (`GetOwnedGames`)
  - [ ] Clear message when a profile is private
  - [ ] Add untracked owned games to the ingest queue
- [ ] Import wishlists (`IWishlistService/GetWishlist`)
  - [ ] `user_wishlist` table
  - [ ] Clear error when a wishlist is private
- [ ] Personal dashboard (wishlist games at all-time low, player-count change
      since the user last played)

## Later

- [ ] Discord deal alerts for watched/wishlisted games
- [ ] Update resume bullets with real numbers from the stats page

## Fun ideas (mostly reuse data already collected)

Anyone can use these — no login required:

- [ ] Backlog roulette — random pick from library never played
- [ ] Game graveyard — biggest player-count drops from peak, with a tombstone
      showing peak vs. current
- [ ] Price guessing game — show a price chart with the last sale hidden,
      guess the discount before reveal
- [ ] Player count race — animated bar chart, top games trading places over
      a week/month
- [ ] Live pulse — a dot next to each game that blinks faster the more
      people are playing right now

These need Steam login (depends on the "Sign in through Steam" item above):

- [ ] Pile of shame — total price of owned-but-never-played games, plus count
- [ ] Wishlist math — cost today vs. at all-time lows, savings from waiting
- [ ] Steam Wrapped — shareable year-in-review card (most-played game, total
      hours, best deal caught)
- [ ] Friend compare — shared owned games + hours vs. a friend, what's on
      sale for you
- [ ] Site badges — e.g. "Bought at the all-time low," "Cleared 5 backlog
      games"

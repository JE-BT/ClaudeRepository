# Lania ledger
 
## Session 1 (explored at year 659 AE, journey day 13)
 
### The Party's position — event
- Anchored to: marker 37 "The Party" (cell 1091); journey "The revenant of Kaharlale", stage 1 "Out of Adrer into the marshes", nearest track point between vertices 23 and 24
- Status: canon
- Connections: The Bayfshear detour; The border crossing; Bayfshear
- Party is at Bayfshear, about 7 mi off the stage 2 track, 466 mi along it
- Arrived early evening of walking day 12 (journey day 13, counting the supply day in Adrer)
### The border crossing — event
- Anchored to: journey stage 1, miles 268–373; cells 1025 → 1024 (Khara) → 1023 (Birad); Kinargzig River; Fearnyard Proselytism zone
- Status: canon (core); draft (details marked)
- Connections: Barakhur; The Fearnyard debt; The Party's position
- The party crossed through the marshes deliberately, to avoid the border posts at Khara and Birad
- Reason: an Adrer-supplied party bound for Ilthiteach, with no bounty or writ yet, could not pass an official post in Wolfrontia
- They crossed the Kinargzig about a mile below Khara after dark, near the end of walking day 8, by flat boat
- They passed Birad at dusk near the end of walking day 9, on the dry neck between river and fen
- Draft: rope and tar bought in Adrer were for fording and sealing packs
### The Fearnyard debt — belief/other
- Anchored to: zone 4 Fearnyard Proselytism (cells on both sides of the Adrer–Wolfrontia border); religion Fearnyard Commandments
- Status: canon
- Connections: The border crossing; Barakhur
- A Fearnyard missioner vouched for the party to the boatman, out of genuine faith
- The party now owes a debt to the church of their enemy's ally
### The Bayfshear detour — event
- Anchored to: burg 172 Bayfshear; Molten road (route 4)
- Status: canon
- Connections: The Party's position; Swangel Fatewell
- Someone followed the party from the border, forcing them out of the fen and onto the road
- The party must hide in Bayfshear for a few days (this puts them behind the journey plan)
- Identity of the follower: open
### Bayfshear — burg
- Anchored to: burg 172, cell 1091; Clearmia Captaincy, Wolfrontia; culture Dail (13)
- Status: canon
- Connections: Fatewell house; Swangel Fatewell
- Bayfshear lives by marsh-hunting: eels, turtles and fowl, trapped and then smoked; this is what "Hunting" means here
- The smoked food goes to Wolfront market
### Fatewell house — household
- Anchored to: building 14 in bayfshear.json (279 m², about 8 m off the Molten road, village centre); house_on_the_hill.json
- Status: draft
- Connections: Swangel Fatewell; Bayfshear
- Largest house on the main road; home of the family that buys the fen catch and runs the smokehouses
- The library is the hub room (accounts and Fearnyard scripture); the kitchen is reached only through the trophy room
- Household: Swangel; her son Cryspell (carts smoked goods to Wolfront), his wife and three children; a hired trapper in the cellar room
- Travellers off the road are sometimes lodged in the ground-floor room for coin
### Swangel Fatewell — person
- Anchored to: Fatewell house; name from namebase 32 (Human Generic)
- Status: canon (existence and stance, by your answer to gap 3); draft (other details)
- Connections: Fatewell house; The Bayfshear detour
- Widow, 58, hunt-master and head of the household (draft)
- Knows the party crossed the border illegally; has not reported them yet and is weighing it
- Draft: her reluctance is economic (Wolfrontia's 23% poll tax, a Captaincy province) rather than disloyal
### Barakhur — person
- Anchored to: Khara (burg 195), Kinargzig River; name from namebase 35 (Dwarven)
- Status: draft
- Connections: The border crossing; The Fearnyard debt
- Khazadur boatman with a flat boat a mile below Khara; works only when the moon is down
### Adrer district names — other
- Anchored to: burg 5 Adrer; adrer.json districts
- Status: canon
- The district names (Night Reach, Clay Court, Greyrise Town, and so on) are loose common-tongue translations of Orkish names
- The Orkish originals are an open gap
### The revenant hunt: plan and motives — journey
- Anchored to: journey "The revenant of Kaharlale"; burg 34 Kaharlale; religion 24 Sect of the Friendly; zone 7 Ayvar Drought
- Status: draft
- Connections: The Party's position
- Three-phase reading of the plan: pass Kaharlale around day 37 without entering; loop north (Phax Mausoleum, Grughird Collection, Krusetlev) to learn and gather; return laden via Nar to approach from Sarprakyurt's one friendly neighbour
- The bounties come from abroad (Krusetlev, Thalasha) because a returning dead thing in the seat of the Blind Phoenix faith is doctrinally charged at home
- Open: who the party is and who sent them; what "bounty posted" means; what they carry on the laden leg; what Kaharlale wants; who is following them
### Contradictions and slippage
- Hiding in Bayfshear for a few days is not in the journey plan; all later stages now run late
- The track passes within a mile of Khara and Birad although the party avoided the posts; resolved by passing both at nightfall
- Bayfshear's burg type "Hunting" disagrees with its trade (smoked fish and tools); resolved by marsh-hunting canon
## Method notes
 
What worked:
- Presenting data first, then an analytical "expanding" section built on it.
- Gap questions numbered, with lettered options and knock-on effects.
- Travel tables with days, miles and places, derived from the file's transport speeds.
- Journey points carry cell ids, so route attributes (state, culture, faith, biome, river, zone) can be read per step; burgs and markers are matched by distance to the polyline.
- Timing arithmetic produces story: both border towns fall exactly at nightfall.
What felt thin or forced:
- The novel-style dialogue scene; the analytical expansion carried more value.
- Household composition was invented with little data support beyond the room count.
Rules of thumb:
- Journey data is the plan; the ledger records what actually happened and the slippage.
- A route that bends away from its target is a motivation clue: note what it passes, what it avoids, and where the transport mode changes.
- Compare treasury and tax figures across states before calling them high or low.
- Watabou exports drop the user's marks; identify buildings by geometry and say so.
- Namebase lists are not in the .map; generate names from Azgaar's repo lists with its Markov method.
 

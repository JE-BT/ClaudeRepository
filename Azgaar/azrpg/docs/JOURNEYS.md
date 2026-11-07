# Journeys

azrpg plays the first journey saved in an Azgaar map. This page explains how a journey is read, so
that you can design one that plays well.

## The parts of a journey

A journey is a list of segments. A segment with the transport **Stay** is a stop: the company
spends that many hours in a place. Any other segment is a leg: travel by that transport, at its
speed and hours per day, along the segment's points.

In the game:

- Each place where a leg ends becomes a **checkpoint**, with a **par time** worked out from the
  plan: legs at their transport's speed and hours per day, stops for their hours, starting at dawn
  on Day 1.
- The stops at a checkpoint become its **tasks** (marked ★). The player does them in person.
- The player may take any route and any means. Arriving at the last checkpoint completes the
  journey. Going straight into a later town skips the checkpoints between.

The journey starts where its first segment begins: in a town, or in the wilds if no town is there.

## Journey types

The journey's type sets the tone, the travellers offered, the size and roles of the company met at
a Gathering, and the reason given for the destination.

| Type | Company met at a Gathering | Own vessel for water and air legs |
|---|---|---|
| Pilgrimage | fellow pilgrim, guide | no |
| Quest | sword-for-hire, guide, healer | no |
| Caravan | caravan master, guard, drover, cook | no |
| Military campaign | sergeant, scout, surgeon, quartermaster | yes |
| Embassy | ambassador, secretary, guard | no |
| Raid | raider, scout, steersman | yes |
| Smuggling run | fence, lookout | yes |
| Courier ride | (rides alone) | no |
| Expedition | surveyor, naturalist, porter | yes |
| Refugee flight | elder, neighbour, child | no |
| Treasure hunt | map-reader, digger | no |
| Monster hunt | tracker, hunter, trapper | no |
| Exile's flight | loyal servant | no |
| Royal progress | courtier, herald, guard, chamberlain | yes |
| Airship voyage | aeronaut, rigger, navigator | yes |
| Arcane errand | apprentice | no |
| Mercenary contract | captain of the company, sergeant, archer | yes |
| Wandering | (alone) | no |

If the type is missing, it is guessed from the journey's name. A name that begins with a person
("Culzan and the road through the forest") makes that person the company's leader, provided the
name is not also a town, state, culture or faith.

## Stops

The stop's wording decides its task. Words are matched anywhere in the stop's name; a stop can
carry more than one task.

| Wording | Task |
|---|---|
| Gathering, Muster, Meet | meet the company |
| Rumours, News, Tidings | listen for rumours; they become leads, with the reasons for the next leg |
| Booking passage, Waiting for a ship, Hire | book a passage or hire a boat at the harbour |
| Loading, Embark, Board, quay | load and board the company's own vessel for the next leg |
| Resupply, Supplies, Provisions, Market | buy supplies at the market |
| Alms | give alms at the temple |
| Rest, Shelter, Inn, A night at (an inn) | take a room at the inn |
| Camp | camp there |
| A night near, Stopped near, at anchor | camp, or anchor if the place is at sea |
| Bounty, Reward, Contract, Commission, Writ | sign it: an advance now, the reward on proof |
| anything else | spend the stop's hours in the town |

## Transports

Transports come from the map's own list (Options → Transports), with their speed, hours per day
and domain.

- **Land** transports walk or ride overland.
- **Water** transports follow navigable water: the sea, lakes, and rivers wide enough for them
  (boats from 40 m³/s, ships from 400 m³/s). Ships call at harbours within a few miles of a town;
  boats also reach river towns.
- **Air** transports fly over land and sea and moor at towns. A **Teleport** leg is crossed at
  once.
- A booked ship or coach keeps its own timetable; a hired boat is the player's to steer; the
  company's own vessel (after a loading stop, or for the types marked above) is boarded at the
  quay with no fare.

## Tips

- Put a stop at the start of a sea leg (booking, waiting for a ship, or loading) so the player
  knows how the company will travel.
- Name stops after what happens there; the wording above is what the game understands.
- Long sea legs in small boats need food: towns sell only part of their stock each week, so plan
  stops at ports along the way.

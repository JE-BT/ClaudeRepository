"""Event texts for the event deck.

Each marker type has texts for the infrastructure colours that suit it (a bridge: land and sea; a
volcano: air only; a mine: land and air). Every colour has a positive (+1) and a negative (-1)
text, so the deck builder can steer each colour's balance. {name} is the marker's name.

The three colours have different risk profiles, so a player's mix of stars shapes their game:
  land  small, steady swings, slightly more bad than good (tolls, mud, bandits)
  sea   large swings both ways (windfalls and wrecks)
  air   mostly good (speed, sight, shortcuts), with rare but heavy losses
Holding stars of several colours lets a player choose which card each star reads, so
multi-modal networks get more control over events.
"""
from __future__ import annotations

# Target share of positive events per colour.
POSITIVE_SHARE = {"land": 0.45, "sea": 0.5, "air": 0.7}

T = dict  # readability

TYPES: dict[str, dict] = {
    "volcanoes": T(label="Volcano", air={
        +1: "Hot updrafts off {name} lift your airship over a whole day's climb. Draw 2 infrastructure cards.",
        -1: "Ash from {name} chokes the envelope. Remove one air infrastructure from a station of yours on this route."}),
    "hot-springs": T(label="Hot springs", land={
        +1: "Your drivers rest their wagons at {name} and come back eager. Gain 2 gold.",
        -1: "Your carters linger in the steam at {name}. This commission pays no income this turn."}, air={
        +1: "Warm air rising from {name} carries you swiftly. This commission pays 2 extra income this turn.",
        -1: "Sulphur fog over {name} forces a detour. Pay 2 gold."}),
    "water-sources": T(label="Spring", land={
        +1: "Fresh water from {name} spares your teams a costly stop. Gain 1 gold.",
        -1: "{name} has run dry and the oxen falter. Pay 1 gold."}, air={
        +1: "You refill the ballast tanks at {name} for nothing. Draw 1 infrastructure card.",
        -1: "A tank filled at {name} turns foul and spoils the cargo. Pay 2 gold."}),
    "mines": T(label="Mine", land={
        +1: "Ore carts from {name} need hauling and pay well. Gain 2 gold.",
        -1: "A cave-in at {name} blocks the road with spoil. This commission pays no income this turn."}, air={
        +1: "The pithead at {name} sells you a lift of cheap iron fittings. Draw 2 infrastructure cards.",
        -1: "Smelter smoke from {name} fouls the rigging. Discard 1 infrastructure card."}),
    "bridges": T(label="Bridge", land={
        +1: "The toll-keeper at {name} waves your wagons across. Gain 1 gold.",
        -1: "Something lives under {name} and wants paying. Pay 2 gold, or this commission pays no income this turn."},
        sea={
        +1: "Your barges shoot the arches of {name} on a spring flood. This commission pays 2 extra income this turn.",
        -1: "A barge strikes a pier of {name} and sinks. Pay 3 gold."}),
    "inns": T(label="Inn", land={
        +1: "Drovers at {name} share news of a fat contract. Draw 1 infrastructure card.",
        -1: "Your drivers drink the week's wages at {name}. Pay 2 gold."}),
    "lighthouses": T(label="Lighthouse", sea={
        +1: "The beacon of {name} brings your fleet in through the night. Gain 3 gold.",
        -1: "{name} is dark tonight and a hull opens on the rocks. Remove one sea infrastructure from a station of yours on this route."}),
    "waterfalls": T(label="Waterfall", land={
        +1: "Mills below {name} buy your spare loads. Gain 1 gold.",
        -1: "The portage around {name} costs a day of hauling. Pay 1 gold."}, air={
        +1: "Mist over {name} hides a smooth river of air. Draw 1 infrastructure card.",
        -1: "Spray from {name} soaks the cargo nets. Pay 2 gold."}),
    "battlefields": T(label="Battlefield", land={
        +1: "Scavengers at {name} sell salvaged harness cheap. Draw 1 infrastructure card.",
        -1: "Old bones on {name} spook the horses. This commission pays no income this turn."}, air={
        +1: "From above, {name} shows a straight line the armies once marched. This commission pays 2 extra income this turn.",
        -1: "A garrison near {name} fires on strange shapes in the sky. Pay 4 gold."}),
    "dungeons": T(label="Dungeon", land={
        +1: "Treasure hunters back from {name} hire your wagons. Gain 2 gold.",
        -1: "Things crawl out of {name} at night and take a horse. Pay 2 gold."}),
    "lake-monsters": T(label="Lake monster", land={
        +1: "Pilgrims hoping to glimpse {name} pay for passage. Gain 1 gold.",
        -1: "The shore road is closed for fear of {name}. Pay 1 gold."}, sea={
        +1: "Your boats cross the lake while {name} sleeps. Gain 3 gold.",
        -1: "{name} rises under a boat. Remove one sea infrastructure from a station of yours on this route."}),
    "sea-monsters": T(label="Sea monster", sea={
        +1: "Whalers chase {name} and pay for your hold space. Gain 3 gold.",
        -1: "{name} drags a ship under. Remove one sea infrastructure from a station of yours on this route."},
        air={
        +1: "From the sky you mark where {name} sleeps, and sell the chart. Gain 3 gold.",
        -1: "{name} snatches at your gondola from the deep. Pay 4 gold."}),
    "hill-monsters": T(label="Hill monster", land={
        +1: "A bounty is posted on {name} and your guards claim it. Gain 2 gold.",
        -1: "{name} scatters a wagon train. This commission pays no income this turn."}, air={
        +1: "Hunters pay well to be flown over the lair of {name}. Gain 2 gold.",
        -1: "{name} leaps at your low-flying airship. Pay 4 gold."}),
    "sacred-mountains": T(label="Sacred mountain", land={
        +1: "Pilgrims bound for {name} fill your empty wagons. Gain 2 gold.",
        -1: "Priests of {name} demand a tithe from passing traders. Pay 2 gold."}, air={
        +1: "The priests of {name} bless your airship. Draw 2 infrastructure cards.",
        -1: "Flying over holy {name} is forbidden. Pay 4 gold in fines."}),
    "sacred-forests": T(label="Sacred forest", land={
        +1: "Keepers of {name} sell you seasoned timber for axles. Draw 1 infrastructure card.",
        -1: "No wheel may cross {name} this month. This commission pays no income this turn."}),
    "sacred-pineries": T(label="Sacred pinery", land={
        +1: "Resin from {name} seals your wagon covers. Gain 1 gold.",
        -1: "The guardians of {name} turn your wagons back. Pay 2 gold."}),
    "sacred-palm-groves": T(label="Sacred grove", land={
        +1: "Festival at {name}: dates and goodwill for every driver. Gain 1 gold.",
        -1: "Offerings at {name} are expected of every caravan. Pay 1 gold."}),
    "brigands": T(label="Brigands", land={
        +1: "Your outriders drive off {name} and the road pays a reward. Gain 2 gold.",
        -1: "{name} hold up a wagon train. Pay 2 gold."}),
    "pirates": T(label="Pirates", sea={
        +1: "A navy cutter scatters {name}; you claim the prize money. Gain 4 gold.",
        -1: "{name} take a ship and its cargo. Pay 2 gold, and this commission pays no income this turn."},
        air={
        +1: "You spot {name} from the sky and sell the warning. Gain 2 gold.",
        -1: "{name} fire on your airship from the masthead. Pay 4 gold."}),
    "statues": T(label="Statue", land={
        +1: "Travellers rub the foot of {name} for luck, and so do yours. Gain 1 gold.",
        -1: "A procession at {name} blocks the road all day. Pay 1 gold."}, air={
        +1: "{name} is a perfect landmark to steer by. Draw 1 infrastructure card.",
        -1: "Your mooring line snags on {name}. Pay 2 gold."}),
    "ruins": T(label="Ruins", land={
        +1: "Dressed stone from {name} paves a soft stretch of road. Gain 1 gold.",
        -1: "A wagon breaks an axle on the old stones of {name}. Pay 2 gold."}, air={
        +1: "From the air the old road through {name} shows plain as a map. This commission pays 2 extra income this turn.",
        -1: "Vents in {name} pull your airship down. Remove one air infrastructure from a station of yours on this route."}),
    "libraries": T(label="Library", land={
        +1: "A clerk at {name} finds a forgotten trading charter. Draw a commission from any state; keep it or put it on the bottom.",
        -1: "Scholars at {name} dispute your road rights. Pay 1 gold."}),
    "circuses": T(label="Circus", land={
        +1: "{name} hires your wagons between shows. Gain 2 gold.",
        -1: "{name} jams every road for a day. Pay 1 gold."}),
    "jousts": T(label="Joust", land={
        +1: "Knights riding to {name} need provisions. Gain 2 gold.",
        -1: "Your best horses are commandeered for {name}. Discard 1 infrastructure card."}),
    "fairs": T(label="Fair", land={
        +1: "You sell spare stock at {name}. Gain 2 gold.",
        -1: "Fair-day tolls at {name} eat your margin. Pay 1 gold."}),
    "canoes": T(label="Canoes", sea={
        +1: "Canoes at {name} lighter your cargo ashore for a song. Gain 3 gold.",
        -1: "A canoe flotilla at {name} blocks the channel. This commission pays no income this turn."}),
    "migration": T(label="Migration", land={
        +1: "{name} leave hides and horn by the road. Gain 1 gold.",
        -1: "{name} close the road for days. This commission pays no income this turn."}, air={
        +1: "Following {name} from above finds you a tail wind. This commission pays 2 extra income this turn.",
        -1: "Birds following {name} foul the propellers. Discard 1 infrastructure card."}),
    "dances": T(label="Dance", land={
        +1: "The dancers at {name} pay your drivers to stay a night. Gain 1 gold.",
        -1: "Your drivers dance at {name} and forget the road. Pay 1 gold."}),
    "mirage": T(label="Mirage", land={
        +1: "{name} hides your caravan from raiders. Gain 1 gold.",
        -1: "Drivers follow {name} into the sand. Pay 2 gold."}, air={
        +1: "From above, {name} is only shimmer; you cut straight across. Draw 2 infrastructure cards.",
        -1: "{name} draws your pilot off course. Pay 4 gold."}),
    "caves": T(label="Cave", land={
        +1: "Cool chambers in {name} keep perishable goods fresh. Gain 2 gold.",
        -1: "Bats from {name} stampede the oxen. Pay 1 gold."}),
    "portals": T(label="Portal", air={
        +1: "The portal at {name} opens for your cargo. This commission pays 3 extra income this turn.",
        -1: "The portal at {name} misfires and a crate is gone. Pay 4 gold."}),
    "rifts": T(label="Rift", land={
        +1: "Strange metal from {name} sells high. Gain 2 gold.",
        -1: "The road near {name} twists back on itself. Pay 2 gold."}, air={
        +1: "The rift at {name} pulls you along like a current. Draw 2 infrastructure cards.",
        -1: "The rift at {name} tears the envelope. Remove one air infrastructure from a station of yours on this route."}),
    "disturbed-burials": T(label="Disturbed burial", land={
        +1: "Grave goods from {name} are sold off cheap. Draw 1 infrastructure card.",
        -1: "Your drivers refuse to pass {name} after dark. This commission pays no income this turn."}),
    "necropolises": T(label="Necropolis", land={
        +1: "Mourners travelling to {name} pay for passage. Gain 2 gold.",
        -1: "The dead of {name} walk the road at night. Pay 2 gold."}, air={
        +1: "Nothing at {name} looks up; you pass in peace. Draw 1 infrastructure card.",
        -1: "Cold mist from {name} freezes the rigging. Pay 4 gold."}),
    "encounters": T(label="Encounter", land={
        +1: "A stranger outside {near} shows your drivers a shortcut. Gain 2 gold.",
        -1: "A stranger outside {near} delays you with riddles. Pay 1 gold."}, sea={
        +1: "A strange ship off {near} trades at a good price. Gain 3 gold.",
        -1: "A strange ship off {near} follows you and spooks the crew. Pay 3 gold."}, air={
        +1: "A stranger on a hilltop near {near} waves you to a hidden mooring. Draw 2 infrastructure cards.",
        -1: "Something from near {near} follows you through the clouds. Pay 4 gold."}),
    "tunnels": T(label="Tunnel", land={
        +1: "The tunnel at {name} saves a mountain pass. Gain 2 gold.",
        -1: "The tunnel at {name} has flooded. This commission pays no income this turn."}),
    "springs": T(label="Spring", land={
        +1: "Fresh water at {name} spares your teams a costly stop. Gain 1 gold.",
        -1: "The spring at {name} is fouled. Pay 1 gold."}),
}

# Types left out of the event deck (campaign markers, not places).
SKIP_TYPES = {"party"}

GENERIC: dict[str, list[tuple[int, str, str]]] = {
    "land": [
        (+1, "Dry roads", "A dry spell firms up every road. Gain 1 gold."),
        (+1, "Good harness", "A saddler sells you harness at cost. Draw 1 infrastructure card."),
        (+1, "Return load", "Your empty wagons find a return load. Gain 2 gold."),
        (+1, "Market rumour", "A drover sells you news of a rich contract. Draw a commission from any state; keep it or put it on the bottom."),
        (-1, "Spring mud", "Spring mud swallows the wheels. Pay 1 gold."),
        (-1, "New toll", "A lord sets a new toll on the road. Pay 2 gold."),
        (-1, "Lame horses", "Half the teams go lame. This commission pays no income this turn."),
        (-1, "Broken axle", "A loaded wagon breaks an axle. Discard 1 infrastructure card."),
        (-1, "Washed-out ford", "A ford washes out. Pay 1 gold."),
    ],
    "sea": [
        (+1, "Fair winds", "A steady following wind for a week. This commission pays 2 extra income this turn."),
        (+1, "Rich catch", "Your crews net a rich catch on the side. Gain 3 gold."),
        (+1, "Salvage", "Your ship finds a drifting cargo. Gain 4 gold."),
        (+1, "Shipwright's favour", "A shipwright owes you a favour. Draw 2 infrastructure cards."),
        (-1, "Gale", "A gale strips the rigging. Pay 3 gold."),
        (-1, "Becalmed", "Your ships lie becalmed. This commission pays no income this turn."),
        (-1, "Wreck", "A ship goes down with all its cargo. Remove one sea infrastructure from a station of yours on this route."),
        (-1, "Harbour dues", "The harbour master doubles the dues. Pay 3 gold."),
        (+1, "Convoy", "A navy convoy shepherds your ships for free. Gain 2 gold."),
        (+1, "Spice smuggler", "A smuggler pays well for a quiet berth in your hold. Gain 4 gold."),
        (+1, "New chart", "A pilot sells you a chart of a faster channel. This commission pays 3 extra income this turn."),
        (+1, "Prize court", "A prize court awards you a captured hull. Draw 2 infrastructure cards."),
        (+1, "Spring tides", "Spring tides float your ships over every bar. Gain 3 gold."),
        (-1, "Fog bank", "Fog holds your ships in harbour for a week. This commission pays no income this turn."),
        (-1, "Mutiny", "The crew mutinies over short rations. Pay 4 gold."),
        (-1, "Shipworm", "Shipworm riddles a hull. Discard 1 infrastructure card, and pay 1 gold."),
        (-1, "Quarantine", "A port quarantines your ships. This commission pays no income this turn."),
        (-1, "Press gang", "The navy presses your best sailors. Pay 3 gold."),
    ],
    "air": [
        (+1, "Tail wind", "A tail wind all the way. This commission pays 2 extra income this turn."),
        (+1, "Clear skies", "Clear skies and quick passages. Draw 2 infrastructure cards."),
        (+1, "Rich passenger", "A wealthy passenger pays for a seat. Gain 3 gold."),
        (+1, "Spare gas", "A rival sells you gas cheaply. Gain 2 gold."),
        (+1, "Survey contract", "A cartographer hires your airship for a survey. Draw a commission from any state; keep it or put it on the bottom."),
        (-1, "Thunderhead", "A thunderhead forces you down. Pay 4 gold."),
        (-1, "Torn envelope", "The envelope tears on landing. Remove one air infrastructure from a station of yours on this route."),
        (+1, "Royal post", "The crown hires your airship to carry the post. Gain 3 gold."),
        (+1, "Aerial survey", "Your crew charts a shorter line between two towers. This commission pays 2 extra income this turn."),
        (+1, "Spare parts", "A broken-up airship sells you its fittings. Draw 2 infrastructure cards."),
        (-1, "Lightning", "Lightning strikes the mooring mast. Pay 4 gold."),
    ],
}

# Which colours a marker type can produce when it is not in TYPES.
DEFAULT_COLOURS = ("land",)


GENERIC_NAMES = {"dungeon", "pirates", "random encounter", "encounter"}
OFFSHORE = {"pirates", "sea-monsters", "lighthouses", "canoes"}


def names_for(mk: dict, near: str) -> tuple[str, str]:
    """(title, name) for a marker. Azgaar gives some markers only a generic name ("Dungeon",
    "Pirates", "Ruined Fortress"); those are located by the nearest stop instead."""
    mtype = mk.get("type", "")
    label = label_of(mtype)
    raw = (mk.get("name") or "").split(" — ")[0].strip()
    low = raw.lower()
    generic = (not raw or low in GENERIC_NAMES or low == label.lower()
               or low.startswith(("ruined ", "travelling ", "random ")) or low.endswith((" migration", " mirage")))
    if not generic:
        return raw, raw
    prep = "off" if mtype in OFFSHORE else "near"
    noun = low or label.lower()
    if noun.endswith(" migration"):
        noun = "migrating " + noun[:-10]
    return f"{raw or label} {prep} {near}", f"the {noun} {prep} {near}"


def render(template: str, name: str, near: str) -> str:
    s = template.format(name=name, near=near)
    return s[:1].upper() + s[1:]


def label_of(mtype: str) -> str:
    if mtype in TYPES:
        return TYPES[mtype]["label"]
    return mtype.replace("-", " ").rstrip("s").capitalize() or "Place"


def texts_for(mtype: str) -> dict[str, dict[int, str]]:
    """Colour -> {polarity: template} for a marker type (unknown types fall back to land texts)."""
    entry = TYPES.get(mtype)
    if entry:
        return {c: entry[c] for c in ("land", "sea", "air") if c in entry}
    return {"land": {+1: "Locals near {name} trade with your drivers. Gain 1 gold.",
                     -1: "Trouble near {name} slows the road. Pay 1 gold."}}

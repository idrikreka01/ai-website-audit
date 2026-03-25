#
# ABOUTME: Batch runner to enqueue audits from a pasted domain list.
# ABOUTME: Calls POST /audits for each domain and prints session ids.
#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Iterable

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


ENDPOINT = os.getenv("AUDIT_API_URL", "http://localhost:8000/audits")
DEFAULT_MODE = os.getenv("AUDIT_MODE", "standard")


DOMAINS_TEXT = """
# Paste one domain or full URL per line.
# Examples:
# wearetabuu.com
# https://example.com
hannah-corbin.com
emergebariatrics.com
hungheeenergy.com
galactechgear.com
ecoseem.com
chezlapingoods.com
wakacon.com
zevorashop.com
sobeworldco.com
chargenza.com
bisprico.com
shop.easygadgets.com
reboxednready.com
vantacoshop.com
floridashroomking.com
smarthearingaid.com
elderlane.com
zuggaone.com
precisionpropco.com
digimcoach.com
elloura.com
futurestitch.com
tendenciagadget.com
shopmarus.com
kyoprime.com
naturefulsoul.com
pico-shop.com
blamboxco.com
cleansafeproducts.com
techonblue.com
loverlygoods.com
echovibe.life
kpontech.com
posstandsco.com
gekcous.com
daanflash.com
workoutsgear.store
copilot.polakium.com
surron3d.com
acorngeneralstore.com
nutriscanlabs.org
made-by-earth.com
theprocam.us
vomor.com
samadhimoss.com
oli8.com
miniprojexx.com
urblgoods.com
earthhero.com
galaxyoutlaw.com
swift-cube.com
phones4all.com
breu-co.com
sams77.com
highvaluesteals.com
ecovia-france.com
wellvine.com
envozar.com
findmstore.com
ecodropau.com
fridaywellnessco.com
clearcomfortnightguards.com
vxny2k.com
itemsrgb.com
theblueberryfund.com
tech-nexa.store
y2kselect.org
Kr-Desighns.myshopify.com
crazycrayons.com
rewind2k.com
mindstudio.life
fullspec710.com
mykickdry.com
daiwahealth.net
someloops.com
alkiramini.com
edgetechsports.com
ecolivingdirect.com
mussore.com
worldfitnessproject.shop
store.arshon.com
buy.usb.club
jovercover.com
shopmvrk.com
genzpc.com
hmblrslnt.com
raemaxx.com
shopredbeam.com
nolagpro.com
noelsoul.com
radicalbroccoli.shop
bernalretro.com
828official.com
cotechzone.com
melco.store
ricelove.com
xtendoletsgo.com
boompodstag.com
madeset.com
haroutine.com
beemstudios.us
theearbuddy.com
airsnapsconnect.com
ezzflow.com
nomad-lim.com
saintholiday.com
naturevogue.store
atomvibegroup.com
jinseigear.com
lestoilesdularge.com
hopeandvintage.com
56ea3c.myshopify.com
keikico.com
zyntekglobal.com
caseprotect.store
timetreez.com
actuallyearth.com
utoplike.com
optifylife.com
stockedupshops.com
luciddreamsllc.com
sibodigital.com
poecameradirect.com
forallnutrition.com
electroguru.store
itsrealbasic.myshopify.com
mastergenie.shop
sidequest92.com
elefront.com
shopsmartbuy.store
cfc3d.com
trackandprep.com
nectarandbloomfloral.com
smartgadgetgear.com
taptempokeyboard.com
mypedalpods.com
domyfanusa.com
betterbuys.net
neonpandaled.com
armlabz.com
miterro.com
drinkhappypop.com
titanicdenim.com
labelphaze.com
eedestickers.com
blacklabelrentals.com
todaywellspent.com
allthingshemp510.com
lamacaaxes.com
ecomysticmarket.com
lcof.com
ataraclifestyle.com
pyepro.us
zhenabia.com
us.mayumasa.com
mobileaccessorymall.com
shopprogressive.com
gladesshoes.myshopify.com
andreinanaturestore.com
flexmart.org
gr8.us
magnetifyu.com
glowee-smile.com
cypressconnect.store
xn--pk-xkaa.com
luxprotools.com
goldessparis.com
recycleforveterans.shop
odinsinnovations.com
gadgetzz.store
sohomdstore.com
nerwave.shop
yoofuel.com
beefriendly.com
flextechakt.com
plasterd.com
ecofills.net
committedhp.com
besunset.com
alleosuperchar.com
quboshop.com
marysjane.com
thenanocord.com
the-standard.us
projectlala.com
pristineventures0.com
lilcshoppe.com
vayufy.com
doabrand.com
friendlydesignworks.com
tvliftkit.com
sanctuarybeautyco.shop
lightningfast.shop
acefitgear.store
haotiangr.com
pinkypillow.shop
ryvix.site
self2solar.com
unicareshop.com
showerfloss.com
pocketbookstrategist.com
nerdenough.shop
infinitysaltair.com
laysun.com
he3dprinting.com
norcalcarbon.com
magstackarc.com
consciousswag.com
eupherbia.com
legacywatches.com
brothmasters.com
flash-shop.eu
nee3d.com
livescribe-edu.com
lulamena.com
whitecloakproxy.com
ethicalfinds.com
dreamwavepro.com
vibcrafter.com
rebsbags.com
shoddyrc.com
projectvoidstar.com
keligreen.com
graffitiremovalinc.com
novanaofficial.com
sarrafstore.com
wynlabs.com
gabenzogadgets.com
soulvibrance.com
cleanfin.surf
leftwingtshirts.com
adamsonglobal.com
brandtek.com
bthree2.com
tizag.shop
zivaratech.com
pristinesprays.com
infinitygearco.com
carboncoastal.com
ponoprobiotics.com
shoplumisnap.com
stillstrongco.com
ceefh.com
enjoyholywater.com
renewvoltsystems.com
henriks-shop.com
foreverevergreen.us
a-starspire.com
shopelevon.com
invasivespeciesusa.com
retromaniaofficial.com
luxearora.com
clipcam.store
teknexia.com
kudzucollective.us
medi-tins.com
dear-survivor.com
saffronandserai.com
btrtec.com
vorixane.store
aneelectrics.com
doctorhoeflinger.com
direct.raspberrypi.com
vmrcparts.com
buyorenda.com
creativecardstickers.com
matesproducts.com
timthrive.com
dsdetector.com
bio360.com
notaurex.store
qorelogiq.com
"""



def _iter_lines(text: str) -> Iterable[str]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def _normalize_to_url(value: str) -> str:
    v = value.strip()
    if v.startswith("http://") or v.startswith("https://"):
        return v
    return f"https://{v}"


def _read_domains_from_file(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def _post_audit(url: str, *, mode: str, api_key: str | None) -> tuple[int, dict[str, object] | None]:
    body = json.dumps({"url": url, "mode": mode}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        return resp.status, parsed


def main(argv: list[str]) -> int:
    file_path = None
    delay_seconds = float(os.getenv("AUDIT_DELAY_SECONDS", "0.5"))
    limit = None
    offset = 0
    mode = DEFAULT_MODE
    api_key = os.getenv("API_SECRET_KEY")

    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--file" and i + 1 < len(argv):
            file_path = argv[i + 1]
            i += 2
            continue
        if arg == "--delay-seconds" and i + 1 < len(argv):
            delay_seconds = float(argv[i + 1])
            i += 2
            continue
        if arg == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
            continue
        if arg == "--offset" and i + 1 < len(argv):
            offset = int(argv[i + 1])
            i += 2
            continue
        if arg == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]
            i += 2
            continue
        if arg in {"-h", "--help"}:
            print(
                "Usage: python3 run_audit_domains.py [--file domains.txt] "
                "[--offset N] [--limit N] [--delay-seconds S] [--mode standard|debug]",
                file=sys.stderr,
            )
            return 0
        print(f"Unknown argument: {arg}", file=sys.stderr)
        return 2

    if file_path:
        raw_domains = _read_domains_from_file(file_path)
    else:
        raw_domains = list(_iter_lines(DOMAINS_TEXT))

    urls: list[str] = []
    seen: set[str] = set()
    for raw in raw_domains:
        url = _normalize_to_url(raw)
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    if offset < 0 or offset >= len(urls):
        print("Offset out of range.", file=sys.stderr)
        return 2

    start = offset
    end = len(urls) if limit is None else min(len(urls), offset + limit)
    urls = urls[start:end]

    total = len(urls)
    if total == 0:
        print("No domains to process.", file=sys.stderr)
        return 2

    print(f"POST {ENDPOINT}")
    print(f"Mode={mode} DelaySeconds={delay_seconds} Count={total}")

    ok = 0
    failed = 0
    for idx, url in enumerate(urls, start=1):
        try:
            status, payload = _post_audit(url, mode=mode, api_key=api_key)
            session_id = None
            if isinstance(payload, dict):
                session_id = payload.get("id")
            print(f"[{idx}/{total}] {url} -> status={status} session_id={session_id}")
            ok += 1
        except urllib.error.HTTPError as e:
            try:
                err_raw = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_raw = str(e)
            print(f"[{idx}/{total}] {url} -> HTTPError code={e.code} error={err_raw}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"[{idx}/{total}] {url} -> error={e}", file=sys.stderr)
            failed += 1

        if delay_seconds > 0 and idx < total:
            time.sleep(delay_seconds)

    print(f"Done. ok={ok} failed={failed} total={total}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


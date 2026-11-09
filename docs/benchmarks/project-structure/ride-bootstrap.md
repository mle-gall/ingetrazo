# Ride bootstrap · Phase 1

Headless read of `space_asbuilt_ride.igz` on 2026-11-09. The proposed tree contains **231 nodes**, with **21,616 local placements** to file and **12,547 read-only placements** across the facilities and stairs mounts (including their roots).

Loading the document and resolving its links took **8.271 s**. Computing the proposal took **0.063 s**, including the registry read. Both links resolved. The proposed registry passed validation, and the combined apply command passed construction without execution. The host file size and modification time matched before and after.

## Host proposal

**Topology differs from the design-note expectation.** The saved host folder-parent map places Ride, Track, Supports, Access, Fasteners, Reference and Context at the root. Ride contains only the Ride assembly tag. Bootstrap reproduces those parent relationships. All three Fasteners tags resolve to `class: null`. VIS has six recorded mechanical fasteners among 4,971 placements. Those six keep their records. The two review tags contain four placements, including Groupe#536 under Track › _To review.

Counts include descendants. Each leaf projects to the original tag in its existing folder. Recipes below show the IFC class, allowed classes where applicable, predefined type, object type, registry type, systems and classification codes whenever inferred. Folder nodes have no local recipe. Linked names omit their common source prefix.

```text
Ride  [1]
  Ride assembly  [1]  |  class=null
Track  [151]
  Track Sections  [81]  |  class=IfcMember; classes_allowed=IfcMember, IfcElementAssembly
  Track/Supports Connectors  [1]  |  class=null
  Track ties  [41]  |  class=IfcMember; predefined_type=USERDEFINED; object_type=Track tie; type=track_tie; systems=track; classifications=discipline/S, ride_kinds/TRK.TIE
  Rails  [18]  |  class=IfcMember; classifications=discipline/S
  Rail joints  [4]  |  class=IfcPlate; predefined_type=USERDEFINED; object_type=Track flange; type=track_joint; systems=track; classifications=discipline/S, ride_kinds/TRK.JNT
  Brakes  [1]  |  class=IfcElementAssembly; predefined_type=USERDEFINED; object_type=Under-tray; type=brake_assembly; systems=track; classifications=discipline/S, ride_kinds/BRK
  Launch system  [1]  |  class=null
  Launch backbone  [1]  |  class=null
  Launch track  [1]  |  class=null
  Launch mechanical  [1]  |  class=null
  _To review  [1]  |  class=null
Supports  [488]
  Supports  [258]  |  class=IfcColumn; classes_allowed=IfcPlate, IfcColumn, IfcElementAssembly, IfcMember
  Supports Base Plates  [224]  |  class=null
  Foundations  [2]  |  class=IfcSlab; classes_allowed=IfcSlab, IfcFooting; systems=supports; classifications=discipline/S, ride_kinds/FND
  Station substructure  [4]  |  class=IfcElementAssembly; predefined_type=USERDEFINED; object_type=Substructure; type=substructure; systems=supports; classifications=discipline/S, ride_kinds/SUP.FRM
Access  [7,306]
  Catwalks  [7,306]  |  class=null
  Stairs  [0]  |  class=null
Fasteners  [13,646]
  VIS  [4,971]  |  class=null
  ÉCROUS  [4,998]  |  class=null
  RONDELLES  [3,677]  |  class=null
Reference  [21]
  Construction lines  [14]  |  class=null
  Reference images and planes  [4]  |  class=null
  Reference models  [3]  |  class=null
Context  [3]
  117.7 - Slab  [1]  |  class=null
  Concrete context  [1]  |  class=null
  Building context  [1]  |  class=null
  Facilities link  [0]  |  class=null
```

## Linked files

```text
Linked files  [12,547]
  space_asbuilt_facilities  [4,454]
    BUILDING  [0]
      Dome Building  [0]
        Q-Lines  [0]
          Preshow1  [0]
      Concrete Shell  [0]
        Level 117.7  [0]
    Facilities  [25]
      Facilities - 117.7  [23]
        Facilities - 117.7 - Steel Structure  [0]
        Facilities - 117.7 - Phase 1  [6]
          Facilities - 117.7 - Phase 1.1 - Columns  [1]  |  class=null
          Facilities - 117.7 - Phase 1.1 - Beams  [1]  |  class=null
          Facilities - 117.7 - Phase 1.1 - Stabilities  [1]  |  class=null
          Facilities - 117.7 - Phase 1.2 - Beams  [1]  |  class=null
          Facilities - 117.7 - Phase 1.2 - Stabilities  [1]  |  class=null
          Facilities - 117.7 - Phase 1.2 - Columns  [1]  |  class=null
        Facilities - 117.7 - Phase 2  [3]
          Facilities - 117.7 - Phase 2 - Columns  [1]  |  class=null
          Facilities - 117.7 - Phase 2 - Beams  [1]  |  class=null
          Facilities - 117.7 - Phase 2 - Stabilities  [1]  |  class=null
        Facilities - 117.7 - Walls  [14]
          Facilities - 117.7 - Phase 1 CMU Walls  [2]  |  class=null
          Facilities - 117.7 - Phase 2 CMU Walls  [12]  |  class=null
      Facilities - Slabs  [0]
        122.40  [0]
      Mixed facilities - Assembly  [1]  |  class=null
      Facilities - Structure and slabs  [1]  |  class=null
    Observation Deck  [49]
      Observation Deck - Slab  [2]
        Observation Deck - Slab - Steel Deck  [1]  |  class=null
        Observation Deck - Slab - Concrete  [1]  |  class=null
      Observation Deck - Steel  [11]
        Observation Deck - Steel - Columns  [1]  |  class=null
        Observation Deck - Steel - Beams  [1]  |  class=null
        Observation Deck - Steel - Stabilities  [5]  |  class=null
        Observation Deck - Steel - Catwalks  [2]  |  class=null
        Observation Deck - Steel - Guardrails  [1]  |  class=null
        Observation Deck - Steel - Grating  [1]  |  class=null
      Observation Deck - Enveloppe  [27]
        Observation Deck - Enveloppe - Corrugated Steel  [13]  |  class=null
        Observation Deck - Enveloppe - Frames  [3]  |  class=null
        Observation Deck - Enveloppe - Profiles  [11]  |  class=null
      Observation Deck - Distribution  [9]
        Observation Deck - Stud system  [1]  |  class=null
        Observation Deck - Closure profiles  [1]  |  class=null
        Observation Deck - Corrugated Steel  [1]  |  class=null
        Observation Deck - Door  [1]  |  class=null
        Observation Deck - Ceiling - Drywall  [4]  |  class=null
        Observation Deck - CTBX Walls  [1]  |  class=null
    Preshow 2  [217]
      Preshow 2 - Steel  [203]
        Preshow 2 - Stairs  [4]  |  class=null
        Preshow 2 - Columns  [19]  |  class=null
        Preshow 2 - Stabilities  [33]  |  class=null
        Preshow 2 - Beams  [75]  |  class=null
        Preshow 2 - Arches  [26]  |  class=null
        Preshow 2 - Profiles  [46]  |  class=null
      Preshow 2 - Slabs  [2]
        Preshow 2 - Slabs - Concrete  [1]  |  class=null
        Preshow 2 - Slabs - Steel Deck  [1]  |  class=null
      Preshow 2 - Enveloppe  [12]
        Preshow 2 - Enveloppe - Corrugated Steel  [3]  |  class=null
        Preshow 2 - Enveloppe - Profiles  [3]  |  class=null
        Preshow 2 - Enveloppe - Frames  [2]  |  class=null
        Preshow 2 - Enveloppe - Glazing  [4]  |  class=null
    Undeformed_meshes  [0]
    Electro De Velocitor  [15]
      Electro De Velocitor - Steel  [12]
        Electro De Velocitor - Columns  [2]  |  class=null
        Electro De Velocitor - Beams  [5]  |  class=null
        Electro De Velocitor - Stabilities  [2]  |  class=null
        Electro De Velocitor - Guardrails  [1]  |  class=null
        Electro De Velocitor - Grating  [1]  |  class=null
        Electro De Velocitor - Stairs  [1]  |  class=null
      Electro De Velocitor - Enveloppe  [3]
        Electro De Velocitor - Corrugated Steel  [1]  |  class=null
        Electro De Velocitor - Steel Plates  [2]  |  class=null
    Aux Garage  [11]
      Aux Garage - 117.7 - Steel  [3]
        Aux Garage - 117.7 - Columns  [1]  |  class=null
        Aux Garage - 117.7 - Beams  [1]  |  class=null
        Aux Garage - 117.7 - Stabilities  [1]  |  class=null
      Aux Garage - 121.94 - Slab  [0]
      Aux Garage - 121.94  [0]
      Aux Garage - 121.94 - Steel  [3]
        Aux Garage - 121.94 - Columns  [1]  |  class=null
        Aux Garage - 121.94 - Beams  [1]  |  class=null
        Aux Garage - 121.94 - Stabilities  [1]  |  class=null
      Aux Garage - 121.94 - Finishes  [4]
        Aux Garage - 121.94 - Drywall  [1]  |  class=null
        Aux Garage - 121.94 - Drywall Studs  [1]  |  class=null
        Aux Garage - 121.94 - Corrugated Steel Roof  [1]  |  class=null
        Aux Garage - 121.94 - Steel plates  [1]  |  class=null
      Aux Garage - Assembly  [1]  |  class=null
    Preshow 1  [283]
      Preshow 1 - Steel  [262]
        Preshow 1 - Steel - Beams  [85]  |  class=null
        Preshow 1 - Steel - Columns  [14]  |  class=null
        Preshow 1 - Steel - Arches  [32]  |  class=null
        Preshow 1 - Steel - Stabilities  [77]  |  class=null
        Preshow 1 - Steel - Profiles  [52]  |  class=null
        Preshow 1 - Steel - Guardrails  [1]  |  class=null
        Preshow 1 - Steel - Grating  [1]  |  class=null
      Preshow 1 - Enveloppe  [17]
        Preshow 1 - Enveloppe - Corrugated Steel  [7]  |  class=null
        Preshow 1 - Enveloppe - Profiles  [6]  |  class=null
        Preshow 1 - Enveloppe - Frames  [4]  |  class=null
      Preshow 1 - Slab  [4]
        Preshow 1 - Slab - Concrete  [2]  |  class=null
        Preshow 1 - Slab - Steel Deck  [2]  |  class=null
    Slabs  [6]
      Slabs 117.7  [0]
        117.7 - Slab  [0]  |  class=null
      Slabs 122.40  [4]
        122.40 - Phase 1  [2]
          122.40 - Phase 1 - Steel deck  [1]  |  class=null
          122.40 - Phase 1 - Concrete  [1]  |  class=null
        122.40 - Phase 2  [2]
          122.40 - Phase 2 - Concrete  [1]  |  class=null
          122.40 - Phase 2 - Steel deck  [1]  |  class=null
      Slabs 121.94  [2]
        121.94 - Slab - Concrete  [1]  |  class=null
        121.94 - Slab - Steel deck  [1]  |  class=null
    Reference  [50]
      Fake Stairs and slabs - Walk tool  [48]  |  class=null
      Undeformed meshes - Queue line  [2]  |  class=null
    Q-lines  [4]
      Q-lines - Equipment  [4]
        Q-lines - Equipment - Exhaust fans grating  [1]  |  class=null
        Q-lines - Equipment - Separation wall  [1]  |  class=null
        Q-lines - Equipment - Handrails  [1]  |  class=null
        Q-Lines - Equipment - Wall can lights  [1]  |  class=null
    Untagged  [3,793]  |  class=null
  space_asbuilt_stairs  [8,093]
    Stairs A  [9]
      Stairs A - Top Part  [3]
        Stairs A - Top Part - Stairs  [1]  |  class=null
        Stairs A - Top Part - Guardrails  [1]  |  class=null
        Stairs A - Top Part - Beams  [1]  |  class=null
      Stairs A - Columns  [1]  |  class=null
      Stairs A - Beams  [1]  |  class=null
      Stairs A - Stairs  [1]  |  class=null
      Stairs A - Guardrails  [1]  |  class=null
      Stairs A - Assembly  [1]  |  class=null
      Stairs A - Reference  [1]  |  class=null
    Stairs L  [10]
      Stairs L - Beams  [1]  |  class=null
      Stairs L - Columns  [1]  |  class=null
      Stairs L - Guardrails  [1]  |  class=null
      Stairs L - Stairs  [1]  |  class=null
      Stairs L - Stabilities  [1]  |  class=null
      Stairs L - Decking  [1]  |  class=null
      Stairs L - Reference  [3]  |  class=null
      Stairs L - Assembly  [1]  |  class=null
    Stairs H  [4]
      Stairs H - Stairs  [1]  |  class=null
      Stairs H - Guardrails  [1]  |  class=null
      Stairs H - Reference  [1]  |  class=null
      Stairs H - Assembly  [1]  |  class=null
    Stairs E  [7]
      Stairs E - Columns  [1]  |  class=null
      Stairs E - Beams  [1]  |  class=null
      Stairs E - Stairs  [1]  |  class=null
      Stairs E - Decking  [1]  |  class=null
      Stairs E - Guardrails  [1]  |  class=null
      Stairs E - Stabilities  [1]  |  class=null
      Stairs E - Assembly  [1]  |  class=null
    Stairs G  [72]
      Stairs G - Stairs  [21]  |  class=null
      Stairs G - Decking  [4]  |  class=null
      Stairs G - Beams  [8]  |  class=null
      Stairs G - Stabilities  [1]  |  class=null
      Stairs G - Guardrails  [22]  |  class=null
      Stairs G - Columns  [15]  |  class=null
      Stairs G - Assembly  [1]  |  class=IfcElementAssembly; predefined_type=USERDEFINED; object_type=Stair tower; type=stair_tower; systems=access; classifications=discipline/S, ride_kinds/ACC.STR
    Context  [0]
      117.7 - Slab  [0]  |  class=null
    Stairs F  [7]
      Stairs F - Columns  [1]  |  class=null
      Stairs F - Stairs  [1]  |  class=null
      Stairs F - Beams  [1]  |  class=null
      Stairs F - Guardrails  [1]  |  class=null
      Stairs F - Decking  [1]  |  class=null
      Stairs F - Stabilities  [1]  |  class=null
      Stairs F - Assembly  [1]  |  class=IfcElementAssembly; predefined_type=USERDEFINED; object_type=Stair tower; type=stair_tower; systems=access; classifications=discipline/S, ride_kinds/ACC.STR
    Fasteners  [1,948]
      VIS  [1,240]  |  class=null
      ÉCROUS  [664]  |  class=null
      RONDELLES  [44]  |  class=null
    Unidentified  [3]
      _To review  [3]  |  class=null
    Reference  [1]
      Construction lines  [1]  |  class=null
    Untagged  [6,031]  |  class=null
```

## Optional nesting edit

After applying the proposal, these arguments to `set_structure` would place the six folders under Ride in one undo step. The keys below come from this document. The measured proposal retains the original root positions.

```json
{
  "patch": {
    "folder:632e1b3178c04f1f": {
      "parent": "folder:4777a59a3f154e4c"
    },
    "folder:c50b46b3f2d646ac": {
      "parent": "folder:4777a59a3f154e4c"
    },
    "folder:51fb9d13256944ea": {
      "parent": "folder:4777a59a3f154e4c"
    },
    "folder:5caea3aca73a4643": {
      "parent": "folder:4777a59a3f154e4c"
    },
    "folder:98440f18915b4d62": {
      "parent": "folder:4777a59a3f154e4c"
    },
    "folder:fbf58932948d4529": {
      "parent": "folder:4777a59a3f154e4c"
    }
  }
}
```

## Conflicts

The proposal contains **32 conflict entries**. Applying would newly classify **126 local placements**. It would preserve **586 local recorded exceptions** under null-class nodes. The mounted tree identifies **126 further recorded exceptions** for review in the source documents.

| Node | Finding | Detail |
| --- | --- | --- |
| Supports › Supports | mixed classes | IfcPlate × 21, IfcColumn × 107, IfcElementAssembly × 1, IfcMember × 5 |
| Supports › Supports | would newly classify | 124 |
| Supports › Supports | varying predefined_type | No shared default |
| Supports › Supports | varying object_type | No shared default |
| Supports › Supports | varying type | No shared default |
| Supports › Supports | varying systems | No shared default |
| Supports › Supports | varying classifications | No shared default |
| Fasteners › VIS | recorded under null class | IfcMechanicalFastener × 6 |
| Supports › Supports Base Plates | recorded under null class | IfcPlate × 5 |
| Track › Track Sections | mixed classes | IfcMember × 77, IfcElementAssembly × 2 |
| Track › Track Sections | would newly classify | 2 |
| Track › Track Sections | varying predefined_type | No shared default |
| Track › Track Sections | varying object_type | No shared default |
| Track › Track Sections | varying type | No shared default |
| Track › Track Sections | varying systems | No shared default |
| Track › Track Sections | varying classifications | No shared default |
| Access › Catwalks | recorded under null class | IfcMember × 255, IfcSlab × 107, IfcRailing × 204, IfcElementAssembly × 9 |
| Linked files › space_asbuilt_stairs › Untagged | recorded under null class | IfcDiscreteAccessory × 34, IfcColumn × 10, IfcBeam × 39, IfcStair × 8, IfcSlab × 10, IfcRailing × 16, IfcMember × 3, IfcDoor × 1 |
| Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Stairs | recorded under null class | IfcBeam × 1 |
| Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Decking | recorded under null class | IfcSlab × 1 |
| Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Beams | recorded under null class | IfcBeam × 1 |
| Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Guardrails | recorded under null class | IfcRailing × 1 |
| Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Columns | recorded under null class | IfcColumn × 1 |
| Linked files › space_asbuilt_stairs › Unidentified › _To review | review layer | Groupe#70 (`138069e675cc51eb`), Groupe#164 (`a32ed2978cd85510`), Groupe#181 (`fa98fa2fdfbf597a`) |
| Track › Rails | varying object_type | No shared default |
| Track › Rails | varying type | No shared default |
| Track › Rails | varying systems | No shared default |
| Track › Rails | varying classifications | No shared default |
| Track › _To review | review layer | Groupe#536 (`9e032e2e2f524a2d`) |
| Supports › Foundations | mixed classes | IfcSlab × 1, IfcFooting × 1 |
| Supports › Foundations | varying predefined_type | No shared default |
| Supports › Foundations | varying type | No shared default |

## Recorded exceptions by UID and IFC class

Each group below retains its existing record. Host exceptions can be moved to more specific nodes later.

### Fasteners › VIS

IfcMechanicalFastener (6)

```text
8370d637d4914cad  32c99620d92247e2  33a131b45dfd417b  02f484f686ae4d06  e750499bc8384c9d
e6e48c55d063467f
```

### Supports › Supports Base Plates

IfcPlate (5)

```text
9bbe1bfa48f74e46  553a4f1598434f49  af2a0d887845497b  766b9441f3984b2a  9b03c768317f4b28
```

### Access › Catwalks

IfcMember (255)

```text
2d0053e5c51648da  51fb5a483d64487b  74902f239f684936  c4324075c6a54df5  2b7ef3d604244244
ee53d5bf6b204b86  06fc57d49a39466c  1f49c621bc0b468c  5c6fe85bcb214648  38ca6f99a7ef4b2a
f0d074e803054ac2  e95a3e63feed4152  2abe93991c1345e0  ca0a210ad8d44783  03e21a13f2ac406b
b0d6c05a6f274125  3bd957833d904a26  1da6f625a7364e98  ca4ac15bd01f4e04  6767601998b64033
5ed7c0a1121e42bb  bb5a7d2e59e842c4  a7a476b66f3e4370  0d0c4ffb7abf45da  5dd629cb1b7f45bb
d0d58903307741e5  7717f0acc1b74225  86ce1d26d3f54156  709b17bbb7964230  098e4261e8994715
a5c33244afce4887  6c91ff52e54d41a8  d358fb0c66014fa7  f4aa586a9e7b4917  4b51d81386aa4cf7
91a54f2cac494ddd  2755ad6b487a4a1f  75c33894bfa640a0  faa1c00d288145e7  fc658233396b402b
a89228d376824904  a01de3f89d2b4e67  639d759a0d1446ab  fde810939c0640ca  bb5a7cbaa4824fbc
7071123bd0b3444a  bcda5a63457d4bca  f330d27e52ad4133  a8a0f5dee97641dd  a6740c1e9ccb425b
1e40d6a681854202  3721ecea31d64f95  de044863ed5c44ab  5530a1dd5fad469b  290cb2b33029497a
55362553b3ed4b6a  8ebcaa65eb4c4fd3  6008526a76344609  321a95613370473e  3e075a5f9d264d1e
5724608312104a76  a61e2534e0534bcc  9ae444d817c84e56  30f489061894432a  12f2b77d53504c3b
05ae715a65fe43e9  9b5d8ed6c78c46e7  a6bd4ecaaf3349bb  740607ace9344df0  8f2f496d3ab042f8
ba39b286ffec444b  4a54df1991764b2a  980574c116084a6e  8eefb7d31bb74b48  715902012c014822
05cd72a5ee8c44a8  550a14764ab74472  62ae032ae8604756  3943b245bd104653  af56f4ec7fe74794
df4f58cc24f34e5a  1df69a66c7534e99  7fbd441bb5a24067  d02d10e11771443c  152b8ecc49e24d84
dec2e5c7c9d347aa  d17dfe4a6f614198  7443ffd7b8084412  549fa14f91dd4e1a  c40c3bff34a54ffa
0ec7222e1ede4d9f  f1982104aa724a77  9529feac2f784a83  cc79d7ef452b4248  ff0e7c2333774a9e
27981ec27d824bc8  f00cfa7a2ff244fd  5cb8bd4be0ac496e  72910002a5d4432d  6deba042ce8346c6
fd7fb4a95a67484e  2c6284daa2f3406d  8a021b733b1346dd  6b0fb3052a994135  0a57b86d0adb4263
5c555783fc484045  880b5282b43a4340  10419f2d371c4f8f  b457a8163a2545fb  c88e2048fe174e6b
7f1de852f6ee49d1  e062a46d59fb422d  d72a058cd9844e5d  a03ff4e2c4ca480f  1f5ddc2f53ee475f
7f2e29e0478f4e20  29f14f5f675448ad  74939b53e5e94d02  79cf73a68b8c4862  2b233ae423c84e0b
6407daf307fb489e  d4011e09390641bf  b4f51bf7cc3447eb  5cc80327dcb64616  47f822eac66c42b7
e22a8e34f06a4cbb  a18d6552705b4de4  39e24dac06b5402b  975dda419126438a  00309b5cf30a4cda
26c8239710d848ff  8ee4544bb1934cc0  28072d88d9b84bf3  29fb64990a3942ba  73864b4b79ad4a0f
746bf2932ea049d6  3e665ca2ccd947a3  0e21c6aad857444a  f88fd8be092d437f  35a8ab36ad694220
01dee193a27d4937  7bb6e09c456e43b8  94e7371640e64d3d  5ec4b5bf76aa4d92  52c9f1df8a7841d0
a3098b03e7944edc  b2b009c0e0954ec6  7105d339d59c4065  42f46a8146824d5d  c3d8e91417eb4c32
7d410edc819a4c11  baf90d16e9d4492f  b57546235d0643e9  9061db76dd2a49ef  6039a245368e4ff2
77e9b23bd90e4c41  752bf38ada3a44a0  1c73febd39d047b5  9a81a9d230114015  e749ca5982e24370
f5f3187167ea4d2a  a4ef58c50b414021  d374cbcb59d04b5e  a5d6145eaba54695  d7c349094ea64368
9855e75afa4d4033  782a23ebc57a4558  7540136bbe1a450d  cb226bff70ef40b8  5ffe5414d7114374
e9a6f55b53de402d  b3b3f01f6b0340cd  491ccef96ef54bf4  11408da6b75446c6  ca719373826f4ba0
0b7c2d274a4a4a33  84f863c4fb524b43  af5e346d1ad54a14  8b65b074987644f8  5c31fa5aafc14661
404dfe5381a14ce7  e45f5e1abc0646a4  2189059911d04b25  7490f32cdb5c4ca7  ad77b236ee4e4d84
0fc6e86bc6c641c7  968f07293c374fb8  46e8b7d1b7b64029  4dad7e0f95104b6a  4295955f69204cc2
d8fef47e6c9b472c  3db363ee7d064a77  3f2c96c6ccc34021  21662a0b0a9c4a15  ad3d8d6068314fa7
768633fa64484e6b  0c92edb7f0434e35  0357ed731d1d484a  dd3d7d26082e4199  8066437697bc404b
2de0af2a0813438f  eda5965787824b04  ad2b7156de904c03  ebfc298f4084494c  8a1fe2061de649e1
335aa9164ab741f8  3baa8f6f5fa841ae  f81a46725b854508  cb8a5e886d694780  9a1cfae81ce544a3
fd84eb60d70d4dce  af7abdacc898453d  234b5e8758b147e4  6aa98542bf5c4e26  b8be6d4a49af4a8b
d56da57cba4045ef  fd2ea9085ef04ce4  30ebb4a003c949d9  b8b041a9c6da4cfb  a36a4ead74a14a0c
34134492b2b843cb  a931ef2301404614  c91c760a36414262  2773b701236a40c2  9acf7f8b44024673
6a471312550842c7  6363bf7c16364b75  3bad6159830a4a5c  37ad55db356244b6  8a097a3b3cd34384
cb474d851f6c4df9  db7bbff21f8f46d2  828ec0bafa7a4d20  6a2d803ff75441fc  5be6f39b52fd4b2e
188714fbd33747f7  d71062556ec047ab  3cbf05f0186a4e4b  ff872c1417f14220  570332049a6b4eb4
630fdb6f4a314431  f5826370bd724d0e  52839a62df714c60  68b3a70f23a044e0  3945f14f906f424d
7c6a30ab68b649ac  5ffc91322c0748ed  0ec98b6a3b054aba  32c22c21bbed4e54  72d529cb99c84119
3cd741cfd117447c  0192486a0ab342fb  b21463fcbfef46e8  0643299d31364fbe  afbe7ee7ce524b92
```

IfcSlab (107)

```text
f6e739cb06ff456d  a3dc02f8a3f3492b  c3df7718269b4832  e876157ed6d54712  d8c5c2efef88498d
c523a8b4b4d04f81  f175ddaad11b4d78  60d700e4cfec4f8c  d761ee54bbcf4044  3db626e757314a01
11afcfbf9ea8454e  0463bb32a53d4dce  96a78f18ddd041d2  d29804ff06574015  667596dc5c714f5f
845b4a1f45f0410b  d29079f22d5e42f3  3535baaf2b874c60  f6117f5ace35421a  e6c93fd09cbf4fd6
5edb732aea894c0c  08c2c61ee97e4c6c  38971a29b70645cf  c356c89427874cee  759e8320642b437d
ffe03b2f574e45e3  7121d0f24de84655  fb0875115ce24446  541bba8a120c4097  8f896dbc067b40c6
b718f45c5edb41ac  2f5493cff5f7443f  2d68258b84de4096  d26826d8cb394a7a  b84d1b816dc546d5
886c9a37b71a4d29  37bf53919d6c4352  ded37995da104aa9  b275bde594424da7  4395ae63030d454a
9935850c93154abe  141335b0bfac4bab  46f4c193742f41b9  e00bb9a203d44db8  2245f6dd4c8d4c93
a410754440f941c4  0804af16a56d4a8a  0a286c273f954fe5  125489d33d944b1f  ea907845ebcc4547
c8cc7f9ab8914a3e  353660e145004f77  fa6d605be3694408  ae390305041043e9  94bc0e0a196a4c36
aff050cdf3b34677  fd2552ed8f864504  5e08163c66dd48b0  068b5bdf9ce04776  d49e7a7eeb044c41
1d2c57c98f6543ef  c57f4efb57294cfb  47bfae1d6db44aff  a8a21393e88b4de9  5adc8b3272764e35
ec70f36089244c94  f7c1809bb50b424f  0abae17eda364306  a6f4b878e8044eca  3ab0dc71bf4b4c49
8b1db29f574b40f7  2c22fdf1d38047be  29096a11de0e4af8  b54a4d880ed844de  18cb4b3c38514165
2ea309d398a8477e  4600cd9929c8425e  f6a7201bc69c4500  e0e0f57128fb4efb  3492ed28edd64eae
44f1994fe2384d65  b78ea4b002464584  379bc8de601145f6  58170a3b7edf4083  c8af4171938e40cb
ce9ee4dc0a0d412f  746096a5f7ed451f  4c90a766c9144359  f176d6281faa4412  76d0d58a7fa04358
f5d3b4d1db6c457f  0aff4e15e9b84f38  d421a02ddbbc4efb  7a39c9d4ab044bd6  1e8ef11755b14983
0d68b928d6f846c9  8fa2e70092bd4172  22bc0e15415b455a  5106e2e314cc4496  29a1af342e5c44e7
39044f7e4d464cc7  0ddbd75f7a1d4e11  5b89a9a1704e484d  e96f03063a5e4c7d  a7fc30e26e834c99
ca3a0d3ef7b1438a  86ebc5fbcea94a4a
```

IfcRailing (204)

```text
64810015d6924736  4679dd841e764372  8d17812a55c34f05  ac0edfe3808d4ee6  e71e5753049d483e
f92a117ffdab46e9  dc4b5096481d43a1  907fc7786f184ba5  dd38e38c7f2e45f5  6a38e16469c94f6c
98147b3a62da4797  0a2ef3985eac43bb  0f13d2e19b3a4fc0  efb25b41e0484839  2311896cb79a41d4
8d33cbd35aad4c99  b2e03796fb1e4428  360cd4b171cc4be6  2ba16770c00744bd  06d7c5a3172046c9
c21d2b78403e4f85  8811be12999f49d4  6eb5c681432b419e  0f6a813c170a4b55  fc2df54c1eb3410a
a0d3fa5770184340  aad4b6d58709429a  1326e61b233645c8  f77561365d734685  b33d02b7fc7e4869
1a25d5aae28a4b5c  e2970e6a02f84643  5216c312686640a7  26cc478f8c5f4de5  6645003c21bb469b
4160429af92e42aa  0d4c5a5aedc24445  1643e61fd95345ee  ef8f558710564996  34b8418a90df4f6f
fe74ab8579d74462  aca889839ca84b49  6834e43631df45f3  03484f46671c4a37  e9fc4f25aa7442fa
ea8c7419f7ac41d8  5572b1be5e9d4b08  3a7c259dd4d2456d  d1039c0baf5046a1  471a35f5b6274257
5171ebaff09c4192  339e9e09301e473b  7de0a5f02c93439e  3e02bc4b503f481d  dbf262b0110b4586
c4804b048c7b464c  fb6635f3ae5440e0  3f3addfa7c694110  d654a13636d94e9a  f51090e520364aa0
55bfafa985a14084  55052eab4d7d4744  5daa5f2ece094529  e807a01cdf61474a  3dd5d2bb2baa43ce
5f9ac6a2e4774424  3a650fcbb5624433  db88e4079b2b4f83  e98cc806e8954031  2a3f04e06638483e
b65a4977c58e45a2  719df9e7e6da4b7a  9500215bc96f4760  fb1787a6c7c44831  71d966c83cf84e8f
8d12eba9cc054f47  f40d1b55d95744b9  7d4eb39ed5764e18  12dd1c8381cd433f  d11dca19925a4c4f
1fb33b8c17f143f9  d1f7371021134091  5436a51e6bd54232  4caa56566a8c4780  f0718422df0a4390
98cd27b16d35439c  f0d29825d686401f  028d0348c8a54fc6  f91154df7dac47ec  b7e71a12d9de4e9b
66e4a4ddc572432c  5fb8a15c295e402a  b3cde4bdec7e4033  e04a9edade8e42c7  f0e5b186344448d2
11b57846dd9043f3  2d461bf1cb2b4016  92bff935d2d24808  fd1e10a0ac28458e  82721f0dcf6a461b
a2d01d48ad144e7f  1fd700c46e5a4d3a  8797a69dbc5d4a27  ec9cd379690648fd  8d8157c8196b42fe
1391c204359c4819  4f0a0dfa463d4c26  93e9c967d9d14f46  5ae6f137b61d415e  a1278d49c16d42a1
35ba2df34bf64170  2b638a568f754cc2  cdf9cc51a6944db8  9d0eae0cee644bbf  c27867b6409543a2
601d5b850c334433  8c6493d487b24fbf  50e2579b416b4f9f  0227de6b5dcd4721  06f0502001ef4142
36ccd6dc1c8c46ae  69869c5f82f74dcc  7c025420ac2442f4  85b6a0bcc25b47bc  d66e5c5278e148a9
2416f09394654407  3338e316c76a4a83  3e751c8142d84487  6b22959e0d0b4837  6731993d2d634bc8
6e395979c15541c1  c4d7fd038469409b  960ea81fe6b94986  0df5d85268014b81  33515356b58f4b91
3bbc5ecc90e64b19  64ad5252434a4289  9b74b98c9cf142d5  fb63d19bd70d4053  183a7862af3b47f9
79ad20c26ee74ea1  9a28215a1a1e4638  3705f2c92e8b4c11  f2269ad2c3654ec3  85302c67e41c4165
75551926ad914d9b  28cf0227f5d44f1b  ba568dc7c4ea4f11  73232dbd54344a1b  09bd2478a63e4d50
21036c6278904159  ea32c1e990dc4871  7dc77611dbf34226  271471b4603a4fef  35463e59e5514c74
85e4e32719494874  dc6f219b1cc940ff  14193875178e46d2  c6c2466928964ec1  180e9961c0d94907
7c2820031cda4f50  3f1bb1ec293b47b9  205a18c07c6242b5  c48fe11dcf1b454c  79886587687047d5
a754081711074dd8  64ccb607fd2b4d6d  d550b5bcd7314978  c99bba95663e405c  037a18b344b24e15
aaf87e11e3f946ba  3cddb3b930994fbd  b5231be9ca264c93  cf6034112575435b  da6d26bfe61949a0
c28577eb5581463f  9b0faab9e8834700  1f1b5ed68795400e  bad7eec8c78545ea  13fcb9ed51054f71
3384f856d3474475  ffb83ffae30b4a96  e36ff763fa694910  4f7f6b3300084944  e60fce29332d4f4e
fdef4f691a334040  add743c7b1864524  0313f156f8f74455  7517f83173df4634  b751c9012fc04b42
5a00571dad774ffb  e8ce3a28db774844  b45364c19f49406d  1ae12050f5d6475c  5a4bbec805ad4ac0
57929b48a82749dd  d754fed88d424819  a2e36fb79e09467c  e0904e6a88264f8f  b0aec1b5f9d9419b
dee8ca3361e74beb  c049ba13d9354202  20eec975f70d4e3e  9e29f8abe78c41ff
```

IfcElementAssembly (9)

```text
00fd18cf3aae4deb  4ff796c003e149e5  f1f5ef318ce54b22  0fe698f5d88b4d81  809558dc91c14f71
a75b4b5f6c564c09  1d9052a274a549b8  fefdffcf0d0c423e  07f99679779046d3
```

### Linked files › space_asbuilt_stairs › Untagged

IfcDiscreteAccessory (34)

```text
4ad6082476ba5e2f  609e9d9441985e7a  760964788db352a9  8373bae62a205b0f  80138ab5c8c35966
941e89cd9334529e  2059a63232035a96  53a0c2d4b78754fc  654141a80bda5d76  98b16883415a5ba1
23db3c1d66f356ec  22c43a66af245737  ed8cf1e63fdc5e1b  1c7d77579f495503  ab2d4b304ec95214
c1278eb7de465d50  be6f941e0f2d5091  694e55d8abca5566  887b96d58c0f573e  952dfe85c9cb58b5
69aa4b2d876050e4  fab31b96b37d5741  f1ee632b0d755565  0f5f3064c29154ef  d48f901663c25fd1
a24ff66a7eff5afa  9c3fb86bae1e53b4  63fb4763dba752fe  d6942cf10cac5948  aae2a1fc997e56f8
7e76f0c66b18575f  41bfb8c5a86b5132  dfc1500eb433586e  2624ffd6e46453c6
```

IfcColumn (10)

```text
3206b1d77c995e8b  e7d5a74dcc5759e3  084d4a39e4c3586f  beb1c9031fc05200  ae4fa3ce30bd5073
bfb2a991d64654e9  2614b51679945df9  742cc76a426f54c8  9f42f4e2439a5132  7aefbca85adb5a36
```

IfcBeam (39)

```text
182fc1e272d95684  d4b06db4a8fc5a2e  ff27b45e0be85854  2a4fb44556e35fe5  94555862211a5076
5cec8e95de715ff0  75ba3175cfa7557e  2cc83424b6a35341  962feaedb69e5b27  4e85027b701b5aa0
2553993222da5659  f4d53c5ddbf15f92  adfd10edc12057eb  52987ea718055db5  8909fff952c759ad
fe2aeab360285186  1ae79fc76c025f15  f702e9ae18015b2f  6afbc5c476b857e9  ab9fd6dd18215b22
7c42b0334a105a9f  d1474576c3905b77  e4de3bd89f145c9a  1bf97f82110f5413  7bcb473753ed58fa
2e100d2a34f55255  e608697bcf5c5c0e  f4200299f13f54c8  9716348384425a04  47885e2e190a59bd
f78748c4f8fd508d  ef02be0f9f11595b  7283296f45c75f26  fda31b05206a5b8c  05356e3455af550e
88fc3d3e2e055de4  b9305489e4875d96  15dc2a2b140c50fb  eaf0b2b51244536e
```

IfcStair (8)

```text
ce49c6fee0a05a7a  1839f246b79f56f9  e725a933ac365dd7  9627ff31e3dd5ad2  9a03b76b6d95581f
1e694f8a73b55ba7  3bf7781dd9c05317  743df96504655fd3
```

IfcSlab (10)

```text
3573fe72e5585087  3f879380d6b55079  01e0d758e7d654e6  808aac7f09cd5577  d4e3277a71285285
f2c4b1a40007560e  3e4327c48b9c5a3a  c2e09da98fa05e36  8a0ec4a8a94e56ee  75e3a23128a85e85
```

IfcRailing (16)

```text
6ad4ca3c12f35d1f  7ebcda2a5b2859eb  b40392372e37577c  2c939e1b15f651bb  5a0106044e315a4a
62063ad03b20545d  a25abf66b9f95c5f  86e0493962b45afd  b2734b8942245ec2  4ce2143b6959594b
1d02c02a8e3e5f27  7106d79abcb35044  12664a27c2af59ec  6a8bb699bc945511  910274eaffb558e4
2957f46e0ede55cc
```

IfcMember (3)

```text
62f2066537a75b8b  9c5bc2a5f7df5e8d  5a58b12c96815745
```

IfcDoor (1)

```text
143aaf33430c5719
```

### Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Stairs

IfcBeam (1)

```text
0c260d0c2f3c5ee4
```

### Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Decking

IfcSlab (1)

```text
53377b03c9b656de
```

### Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Beams

IfcBeam (1)

```text
e0f22486b6e65724
```

### Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Guardrails

IfcRailing (1)

```text
537dfeaf40465e66
```

### Linked files › space_asbuilt_stairs › Stairs G › Stairs G - Columns

IfcColumn (1)

```text
8d76f4ad275552f0
```

## Reproduction

Use the project Python environment with `QT_QPA_PLATFORM=offscreen`. The half-coverage rule and the preservation of existing records on null-class nodes are documented in [Project Structure](../../project-structure.md).

```python
from pathlib import Path
from time import perf_counter
from core import bim_registry, structure
from core.scene import Scene
from formats.igz import load_into

scene = Scene()
start = perf_counter()
load_into(scene, Path.home() / "Desktop/space_exact/space_asbuilt_ride.igz")
loaded = perf_counter()
proposal = structure.bootstrap(scene, bim_registry.get(scene))
finished = perf_counter()
print(loaded - start, finished - loaded)
```

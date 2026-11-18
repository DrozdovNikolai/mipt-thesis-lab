# Примеры: улучшения и ухудшения

Отбор по изменению числа ошибок medium.en → ATC; это иллюстрация, а не отдельная оценочная выборка. Все строки сохранены в scoring/all-atcosim.tsv.

## Наибольшие улучшения

### atcosim_zf1_06_087_000000_000820 (изменение ошибок -17)

Эталон: hapag lloyd six five three geneva one three three decimal one three fo  standby it s geneva one three three one five good bye

medium.en: Hyperglide 653 Geneva 133.1.34, stand by, it's Geneva 133.15, goodbye.

ATC: lufthansa six five three geneva one three three decimal one three four standby it's a geneva one three three one five good bye

### atcosim_zf2_05_035_000000_000743 (изменение ошибок -15)

Эталон: good afternoon japanair four one nine radar contact descend flight level two five zero the rate at least two thousand until passing three three zero

medium.en: Good afternoon, Japan Air 419 radar contact, this is flight level 250, the radar leads 2000, until passing to E30.

ATC: good afternoon jobair nine four one nine radar contact descend flight level two five zero the rate at least two thousand until passing three three zero

### atcosim_zf3_02_193_000000_000838 (изменение ошибок -15)

Эталон: air france six eight zero good afternoon descend to flight level two five zero rate of descent two thousand five hundred feet or more until passing flight level three zero zero

medium.en: Good afternoon, descent to flight level 250, rate of descent 2500 feet or more until passing flight level 300.

ATC: air france six eight zero good afternoon descend to flight level two five zero rate of descend two thousand five hundred feet or more until passing flight level three zero zero

## Наибольшие ухудшения

### atcosim_sm2_09_064_000000_000350 (изменение ошибок +9)

Эталон: standby

medium.en: Uhm, stand by.

ATC: do you have any chance to land on the runway stand by

### atcosim_zf2_06_088_000000_000467 (изменение ошибок +7)

Эталон: air malta four five zero radar contact ageri zurich east nelli

medium.en: Amorta 4-5-0 radar contact, Agar.0-Gizneli.

ATC: air malta four five zero radar contact agar.e zero eight zero good afternoon ready radar contact radar contact radar contact radar contact

### atcosim_sm2_09_088_000000_000499 (изменение ошибок +6)

Эталон: speed bird nine four november is your callsign

medium.en: Speedbird 9F4 November is your callsign

ATC: nine two five wizz air five three five speed bird nine four november is your call sign

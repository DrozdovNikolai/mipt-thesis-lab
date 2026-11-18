See the following associated paper for description:
Mathieu Edon, Anonymous Author, Stefan Bleiholder, Silvia Poschen, Frederic Palpacuer, Lionel Feugère, Transmission model of aircraft audio chain to generate non-sensitive CVR-like speech, submitted to Forum Acusticum 2026
 
# GENERAL INFORMATION
 
## Dataset title
BLeRIOT-C corpus: CVR-like speech from an IR-based model of aircraft audio transmissions

## Authors
Mathieu Edon, Lionel Feugère

## Affiliations et producteurs
Bureau d'Enquêtes et d'Analyses pour la sécurité de l'aviation civile

## DOI
10.57745/ASYVFP
 
## Contact email
lionel.feugere@bea.aero

## License
BLeRIOT-C corpus: CVR-like speech from an IR-based model of aircraft audio transmissions © 2026 by Mathieu Edon, Lionel Feugère is licensed under CC BY-NC 4.0. To view a copy of this license, visit https://creativecommons.org/licenses/by-nc/4.0/ 

Material used in the present corpus
BLeRIOT-A corpus: raw cockpit speech © 2026 by Mathieu Edon, Lionel Feugère (CC BY-NC 4.0). doi.org/10.57745/NODS6L
  
# METHODOLOGICAL INFORMATION 
Demonstration corpus of CVR-like speech using a single modelled audio chain and flight noise recording.

Corpus of raw speech voice (doi.org/10.57745/NODS6L) was used as input to generate a demonstration corpus of CVR-like pilot-channel speech from an IR-based model of aircraft audio transmissions (ATR72 cockpit acoustics, Holmberg headset microphone, DRAIMS Airbus AMU, FA2100 CVR) and a loud descent flight noise recorded from each aircraft microphone position in an A330-743 aircraft (doi.org/10.57745/ASYVFP).

Software "Mathieu Edon, Lionel Feugère. CVR-speech-generator: Aircraft Audio Chain Simulation in Python. 2026. ⟨hal-05584140⟩" was used to generate the data.

Audio files are 48 kHz 32 bits float WAV.
 
# DATA & FILE OVERVIEW
 
## File naming convention
raw-speech/SubcorpusID_type-precision_sp123.wav
	SubcorpusID: 'BEA' or 'DGA'
	type: type of reading: typically CVR transcript or aircraft checklists
	precision: precision on the type of reading, e.g. A320
	speakerID: sp + 3 figures

## File hierarchy convention
Each WAV file is associated to a transcript in the folder raw-speech_corpus/
 
# DATA-SPECIFIC INFORMATION FOR: raw-speech_metadata.csv
Describes each audio file andspeaker characteristics

## Variable/Column List:
FileName				File name of the audio file
Duration_min				Duration of the audio file in minutes
Content					CVR, Checklists or a particular checklist
Transcription				Transcription availability as PDF or docx file (1 or 0) in /raw-speech_transcript
Subcorpus				BEA or DGA
SpeakerID				Speaker's ID: sp001 to sp012 and sp101 to sp105
SpeakerSex				Speaker's sex: male or female
SpeakerAgeRange				Speaker's age in years
SpeakerExperienceAsPilot_yearsRange	Speaker's Experience As Pilot in years	
SpeakerFlyingHours			Speaker's number of flight hours
SpeakerPPL				Private Pilot Licence of the speaker (1 or 0)
SpeakerCPL				Commercial Pilot Licence of the speaker (1 or 0)
SpeakerATPL				Airline Transport Pilot Licence of the speaker (1 or 0)
SpeakerFlightInstructor			Flight instructor licence of the speaker (1 or 0)
AircraftsPilotedBySpeaker		Aircrafts piloted by the speaker
SpeakerExperienceAsAirTrafficController_yearsRange	Speaker's Experience As air traffic controller in years
SpeakerICAOenglishLevel			Speaker's ICAO english level (0= not passed or unknown, 1=lowest level, 6=highest level)
SpeakerMotherTongue			Speaker's Mother tongue
 

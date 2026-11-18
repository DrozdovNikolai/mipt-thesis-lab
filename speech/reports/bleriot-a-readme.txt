See the following associated paper for description:
Mathieu Edon, Anonymous Author, Stefan Bleiholder, Silvia Poschen, Frederic Palpacuer, Lionel Feugère, Transmission model of aircraft audio chain to generate non-sensitive CVR speech, submitted to Forum Acusticum 2026
 
 
# GENERAL INFORMATION
 
## Dataset title
Mathieu Edon and Lionel Feugère, BLeRIOT-A corpus: raw cockpit speech, 2026
 
## DOI
10.57745/EWXJLT
 
## Contact email
lionel.feugere@bea.aero

## License
BLeRIOT-A corpus: raw cockpit speech © 2026 by Mathieu Edon and Lionel Feugère is licensed under CC BY-NC 4.0. To view a copy of this license, visit https://creativecommons.org/licenses/by-nc/4.0/ 
  
# METHODOLOGICAL INFORMATION 
 
A cockpit-oriented corpus was recorded, bringing French and English pilot vocabulary from French-native speakers (ICAO english level median of 5). They were composed of two sub-corpora, recorded by BEA (civil) and by DGA Essais propulseurs (military).

BEA
Volunteers (9 males and 3 females; 24- to 64-years-old) having an experience as pilot (private, airlines, military; median number of flight hours: 475), or air traffic controller, were recorded while reading airplane take-off and check-lists (Boeing, Airbus; total of 177 min) and non-sensitive transcripts from Airbus airplanes CVRs (total of 47 min).
Speakers wore a headset to hear their voice in feedback as in a cockpit. The measurements was performed in a room with partial audio treatment on walls and an anti sound reflection screen (Reflexound, Plugger Sound) around a low-noise directional microphone (MKH 60 P48, Sennheiser), located at close range of the speaker, and plugged to a portable recorder (H4n Pro, Zoom; 32 bit float wave files at 44.1 kHZ.

DGA
Volunteers (6 males, 22- to 56-years-old) having an experience as pilot (private, flight engineer; median number of flight hours: 100), air traffic controller or CVR analyst, were recorded while reading aircraft check-lists (total of 21 min) as well as non-sensitive transcripts (total of 14 min).
A portable recorder (H6, Zoom; 16 bit float wave files at 44.1 kHz and its integrated stereo microphones were used, located at close range from the speaker. Only the left channels were kept.


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
Describes each audio file

## Variable/Column List:
FileName			File name of the audio file
Duration_min			Duration of the audio file in minutes
Content				CVR, Checklists or a particular checklist
Transcription			Transcription availability as PDF or docx file (1 or 0) in /raw-speech_transcript
Subcorpus			BEA or DGA
SpeakerID			Speaker's ID: sp001 to sp012 and sp101 to sp105
SpeakerSex			Speaker's sex: male or female
SpeakerAgeRange			Speaker's age in years
SpeakerExperienceAsPilot_yearsrange	Speaker's Experience As Pilot in years	
SpeakerFlyingHours		Speaker's number of flight hours
SpeakerPPL			Private Pilot Licence of the speaker (1 or 0)
SpeakerCPL			Commercial Pilot Licence of the speaker (1 or 0)
SpeakerATPL			Airline Transport Pilot Licence of the speaker (1 or 0)
SpeakerFlightInstructor		Flight instructor licence of the speaker (1 or 0)
AircraftsPilotedBySpeaker	Aircrafts piloted by the speaker (separated by comma)
SpeakerExperienceAsAirTrafficController_yearsRange	Speaker's Experience As air traffic controller in years
SpeakerICAOenglishLevel		Speaker's ICAO english level (0= not passed or unknown, 1=lowest level, 6=highest level)
SpeakerMotherTongue		Speaker's Mother tongue
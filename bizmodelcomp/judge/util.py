import random

def get_next_pitch_to_judge(competition, judge):

    if judge.user == competition.owner:
        #is organizer...
        organizer = judge.user
    
        #get all pitches from this comp
        pitches = competition.current_phase.pitches(num=-1)

        #get all pitches not yet judged by me
        unjudged = []
        for pitch in pitches:
            was_judged_by_me = False
            for j in pitch.judgements.all():
                if j.judge.user == organizer:
                    was_judged_by_me = True
            if not was_judged_by_me:
                unjudged.append(pitch)
        pitches = unjudged

    else:
        pitches = competition.current_phase.pitches_to_judge()

    if competition.current_phase.pitch_type == "live pitch":
        #for live pitches we assume the pitches are listed sequentially and
        #then just go through them in order
        index = 0

    elif len(pitches) > 1:
        index = random.randrange(0, len(pitches)-1)

    else:
        index = 0

    try:
        return pitches[index]
    except:
        return None

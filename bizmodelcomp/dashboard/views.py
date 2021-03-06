from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q

from competition.models import *
from judge.models import *
from dashboard.forms import *
from dashboard.util import *
from userhelper.models import UserProfile
from emailhelper.models import *
from emailhelper.util import send_bulk_email

import charts.util as chart_util
from datetime import datetime
import time
import smtplib


@login_required
def begin_judging(request, comp_url):

    try:
        competition = Competition.objects.get(hosted_url=comp_url)
    except:
        return HttpResponseRedirect('/dashboard/')

    if competition.owner != request.user:
        return HttpResponseRedirect('/dashboard/')

    competition.current_phase.is_judging_enabled = True
    competition.current_phase.save()

    return HttpResponseRedirect('/judge/%s/' % competition.hosted_url)



@login_required
def next_phase(request, comp_url):

    try:
        competition = Competition.objects.get(hosted_url=comp_url)
    except:
        return HttpResponseRedirect('/dashboard/')

    if competition.owner != request.user:
        return HttpResponseRedirect('/dashboard/')

    phases = competition.phases()
    i = competition.current_phase.phase_num()
    if i < len(phases):
        next_phase = phases[i]
        competition.current_phase = next_phase
        competition.save()

    return HttpResponseRedirect('/dashboard/%s/manage' % comp_url)



    
@login_required
def overall_dashboard(request):

    #grab all the competitions they own
    competitions = Competition.objects.filter(owner=request.user)
    inactive_competition = []

    #make sure the organizer is assigned as a judge for all his competitions
    for competition in competitions:
        try:
            if JudgeInvitation.objects.filter(competition=competition, user=competition.owner).count() == 0:
                owner_judge = JudgeInvitation(competition=competition,
                        email=competition.owner.email,
                        has_received_invite_email=True,
                        user=competition.owner)
                owner_judge.save()
        except:
            pass

    for invite in JudgeInvitation.objects.filter(user=request.user):

        #grab any additional competitions they're a judge for, but don't own
        if not invite.competition in competitions:

            if not invite.this_phase_only:
                #invite is for whole competition
                competitions.append(invite.competition)

            elif invite.this_phase_only == competition.current_phase:
                #invite is for a particular phase, and that phase is active
                competitions.append(invite.competition)

            else:
                #we are judging a non-active part of the competition
                inactive_competitions.append(invite.competition)


    for competition in competitions:

        judge = None

        try:
            judge = JudgeInvitation.objects.get(user=request.user, competition=competition)
        except:
            if request.user is competition.owner:
                #organizers are auto-judges
                judge = JudgeInvitation(user=request.user,
                                        competition=competition,
                                        email=request.user.email,
                                        has_received_invite_email=True)
                judge.save()

        if judge and competition.current_phase:

            #they should always be at least a judge for every competition that shows up, and 
            #sometimes also an organizer
            competition.judged_pitches = competition.current_phase.judgements(for_judge=judge, num=5)
            competition.unjudged_pitches = competition.current_phase.pitches_to_judge(for_judge=judge, num=5)
    
    return render_to_response("dashboard/overall_dashboard.html", locals())





@login_required
def send_competition_feedback(request):
    
    competition = request.user.get_profile().competition()

    subject = "E Challenge feedback"
    from_email = "london.e.challenge@gmail.com"

    message_template = """\
Hello ++team name++,

Thanks for being a part of the %s. Everyone did great work and we look forward to seeing these ideas grow into successful companies.

Below you'll find the feedback from judges -- it's only sent to one person per team, so please share it with your teammates. It's un-edited and was written on the fly, so apologies in advance if you receive something that's overly obscure. And remember that you are more than welcome to follow up with the judges if you'd like additional info.

Your business plan was scored in the __++online rank++ third__ of the scores and your live pitch was in the __++live rank++ third__.

__Business plan: Positive__

++online positive++

__Business plan: To Improve__

++online negative++

__Live pitch: Positive__

++live positive++

__Live pitch: To Improve__

++live negative++

Sincerely,

%s team
""" % (competition.name, competition.name)

    #make the email
    bulk_email = Bulk_email(competition=competition,
            tag="feedback",
            subject=subject,
            message_markdown=message_template)
    bulk_email.save()

    email = bulk_email

    #TODO: un-hardcode plz
    pitches = Pitch.objects.filter(phase=7)

    live_scores = [] 
    online_scores = []

    for pitch in pitches:
        live_scores.append(pitch.average_score())
    for pitch in Pitch.objects.filter(phase=3):
        online_scores.append(pitch.average_score())

    live_scores.sort()
    online_scores.sort()

    i = 0

    team_name = Sub_val(email=bulk_email,
           key="++team name++")
    team_name.save()

    online_negative = Sub_val(email=bulk_email,
            key="++online negative++")
    online_negative.save()

    online_positive = Sub_val(email=bulk_email,
            key="++online positive++")
    online_positive.save()

    live_negative = Sub_val(email=bulk_email,
            key="++live negative++")
    live_negative.save()

    live_positive = Sub_val(email=bulk_email,
            key="++live positive++")
    live_positive.save()

    online_rank = Sub_val(email=bulk_email,
            key="++online rank++")
    online_rank.save()

    live_rank = Sub_val(email=bulk_email,
            key="++live rank++")
    live_rank.save()

    for pitch in pitches:
        online_pitch = Pitch.objects.filter(phase__id=3).get(team__owner__email=pitch.owner.email)

        online_position = online_scores.index(online_pitch.average_score())
        live_position = live_scores.index(pitch.average_score())

        rank = "top"
        if online_position < len(online_scores) / 3:
            rank = "bottom"
        elif online_position < len(online_scores) * 2 / 3:
            rank = "middle"

        val = Val(order=i, val=rank, sub_val=online_rank)
        val.save()

        rank = "top"
        if live_position < len(live_scores) / 3:
            rank = "bottom"
        elif live_position < len(live_scores) * 2 / 3:
            rank = "middle"

        val = Val(order=i, val=rank, sub_val=live_rank)
        val.save()

        #who we're shipping it to
        recipient = Email_address(order=i,
                bulk_email=bulk_email,
                address=pitch.team.owner.email)
        recipient.save()

        #team name
        val = Val(order = i,
                val=pitch.team.name,
                sub_val=team_name)
        val.save() 

        #online negative: 74
        feedback = get_feedback_for_question(74, pitch)
        val = Val(order = i,
                val=feedback,
                sub_val=online_negative)
        val.save() 

        #online positive: 75
        feedback = get_feedback_for_question(75, pitch)
        val = Val(order = i,
                val=get_feedback_for_question(75, pitch),
                sub_val=online_positive)
        val.save() 

        #live negative: 77
        val = Val(order = i,
                val=get_feedback_for_question(77, pitch),
                sub_val=live_negative)
        val.save() 

        #live positive: 76
        val = Val(order = i,
                val=get_feedback_for_question(76, pitch),
                sub_val=live_positive)
        val.save() 

        i += 1
        
    return render_to_response('emailhelper/review_email.html', locals())
    

    
@login_required
def announce_judging_open(request, comp_url):

    TAG = "Judging open"

    competition = get_object_or_404(Competition, hosted_url=comp_url)
    if competition.owner != request.user:
        return HttpResponseRedirect('/no_permissions/')

    email = None
    try:
        #if we've already crafted an email for this phase, load it up
        email = Bulk_email.objects.get(competition=competition, phase=competition.current_phase, tag=TAG)
        email.save()
        
        if email.sent_on_date is not None:
            return HttpResponseRedirect("/dashboard/email/%s/" % competition.hosted_url)
        else:
            return HttpResponseRedirect("/dashboard/email/%s/confirm/%s/?next=/dashboard/%s/manage/" % (competition.hosted_url, email.id, competition.hosted_url))

    except:
        subject = "Judging is open - %s" % competition.name
        from_email = "london.e.challenge@gmail.com"

        message_template = """\
Hello,

Judging for %s has begun. We have %s applications to judge, which you can view here:

%s

When you press the 'start judging' button you'll be automatically provided with the next unjudged plan. Alternately, you can view the full list of pitches to select a particular one.

Thanks very much for the help.

%s team
""" % (competition.name, Pitch.objects.filter(phase=competition.current_phase).count(), 'http://www.nvana.com/judge/', competition.name)
    
        recipients = []
        #send to all judges from this phase
        for judge in competition.current_phase.judges():
            recipients.append(judge)

        email = Bulk_email(competition=competition,
                phase=competition.current_phase,
                tag="judging open",
                message_markdown=message_template,
                subject=subject)

        email.save()

        #create recipient list
        for i, judge in enumerate(recipients):
            r = Email_address(bulk_email=email,
                    address=judge.email,
                    user=judge.user,
                    order=i)
            r.save()

        return HttpResponseRedirect("/dashboard/email/%s/confirm/%s/?next=/dashboard/%s/manage/" % (competition.hosted_url, email.id, competition.hosted_url))

            ##update phase todo progress
            #steps = phase.setup_steps()
            #steps.announced_judging_open = True
            #steps.save()
            #
            ##the setup_steps flag is just for UI. this is the real one
            #phase.is_judging_enabled = True
            #phase.save()
            #
            #return HttpResponseRedirect('/dashboard/phase/%s/' % phase.id)


    #return render_to_response('emailhelper/review_email.html', locals())



@login_required
def announce_applications_open(request, comp_url):

    competition = get_object_or_404(Competition, hosted_url=comp_url)
    if competition.owner != request.user:
        return HttpResponseRedirect('/no_permissions/')

    TAG = "Applications open"

    email = None
    try:
        #if we've already crafted an email for this phase, load it up
        email = Bulk_email.objects.get(competition=competition, phase=competition.current_phase, tag=TAG)
        email.save()
        
        if email.sent_on_date is not None:
            return HttpResponseRedirect("/dashboard/email/%s/" % competition.hosted_url)
        else:
            return HttpResponseRedirect("/dashboard/email/%s/confirm/%s/?next=/dashboard/%s/manage/" % (competition.hosted_url, email.id, competition.hosted_url))

    except:

        #if we the email doesn't exist, load it
        from_email = "competitions@nvana.com"

        subject = "%s - Applications open" % competition.name

        message_template = """Hello,

Applications to __%s__ are now open. You may apply at the following link:

http://www.nvana.com/%s/

You'll be able to submit and revise your application until __%s__. Only one person per team needs to submit an application. 

Thanks for participating. We look forward to your submissions. Please contact the organizer if you have any questions.

Sincerely,

%s team
""" % (competition.name, competition.hosted_url, competition.current_phase.deadline.strftime("%A, %B %d, %H:%M %p"), competition.name)

        email = Bulk_email(competition=competition,
                phase=competition.current_phase,
                tag=TAG,
                subject=subject,
                message_markdown=message_template)
        email.save()

        recipients = []
        for founder in competition.current_phase.applicants():
            if founder.email:
                recipients.append(founder)

        #create recipient list
        for i, recipient in enumerate(recipients):

            r = Email_address(bulk_email=email,
                    address=founder.email,
                    user=founder.user, 
                    order=i)
            r.save()

        return HttpResponseRedirect("/dashboard/email/%s/confirm/%s/?next=/dashboard/%s/manage/" % (competition.hosted_url, email.id, competition.hosted_url))

    ##mark the step as ticked off
    #print 'setting announced_applications for phase %s' % phase.id
    #setup_steps = phase.setup_steps()
    #setup_steps.announced_applications = True
    #setup_steps.save()
    #print 'saved announed_applications: %s' % phase.setup_steps().announced_applications
    #
    #return render_to_response('emailhelper/review_email.html', locals())



@login_required
def set_current_phase(request, phase_id):

    phase = get_object_or_404(Phase, id=phase_id)

    if phase.competition.owner != request.user:
        return HttpResponseRedirect('/dashboard/')

    phase.competition.current_phase = phase
    phase.competition.save()

    return HttpResponseRedirect('/dashboard/phase/%s' % phase_id)

    

def create_new_comp_for_user(user):

    key = None
    while True: 
        #find a unique url for the competition
        key = rand_key(6)
        try: 	Competition.objects.get(hosted_url=key)
        except:	break
        
    competition = Competition(owner=user, hosted_url=key)
    competition.save()
    current_phase = Phase(competition=competition)
    current_phase.save()
    competition.current_phase = current_phase
    competition.save()

    if not user.get_profile():
        #ensure old accounts have a profile
        profile = UserProfile(user=request.user)
        profile.selected_competition = competition
        profile.save()

    return competition


def setup(request, comp_id=None, step_num="1"):
    
    #custom auth handling bc we generally want to redirect to register rather than login
    if not request.user.is_authenticated():
        if step_num == "1":
            return HttpResponseRedirect("/accounts/register/?next=/dashboard/setup/%s/" % step_num)
        else:
            return HttpResponseRedirect("/accounts/login/?next=/dashboard/setup/%s/" % step_num)


    alert = ""

    #templates = { "1": "dashboard/setup_comp_details.html",
    #        "2": "dashboard/setup_app_reqs.html",
    #        "3": "dashboard/setup_distribution.html" }

    templates = { "1": "dashboard/setup_comp_details.html" }

    form = None

    if request.method == "POST":

        if step_num == "1":

            #create new competition for user with inputted details
            competition = create_new_comp_for_user(request.user) 

            if not competition:
                #display error if non-unique hosted URL
                alert = "That URL has already been used by someone. Try something different?"

            #create model form from POST data
            form = CompetitionInfoForm(request.POST, instance=competition)

            #save instance
            try:
                form.save()

                #if success, set as user's current competition
                request.user.get_profile().current_competition = competition
                request.user.get_profile().save()

            except:
                                    
                if competition:
                    #delete comp we just created since there was an error saving data
                    #and we don't want half-baked multiples floating around
                    competition.delete()
                    
                alert = "That URL has already been used by someone. Try something different?"


        elif step_num == "2":

            competition = get_object_or_404(Competition, hosted_url=comp_url)

            #save application requirements

        elif step_num == "3":

            #nothing to do, submission is just used to advance to
            #next step
            pass


        #go to next step
        try:
            next_step = ""
            if alert:
                next_step = step_num
                print 'alert: %s' % alert
            else:
                next_step = str(int(step_num) + 1)

            print 'next step: %s' % next_step
            temp = templates[next_step]
            print 'temp: %s' % temp
            #got a submission for the current step, move on to next one
            return HttpResponseRedirect('/dashboard/setup/%s/' % next_step)

        except:
            print 'except: %s' % sys.exc_info()[0]
            #no more steps to show, so go to dashboard
            return HttpResponseRedirect('/dashboard/')

    else: #request.method==GET
        try:
            temp = templates[step_num]

            if step_num == "1":
                form = CompetitionInfoForm()

            elif step_num == "2":
                pass

            print 'get rendering step: %s' % step_num

            #for a GET, just render the relevant template
            return render_to_response(templates[step_num], locals())

        except:
            print 'get except: %s' % sys.exc_info()[0]
            #can't find what they're looking for, back to dash 
            return HttpResponseRedirect('/dashboard/')



def set_question_options(request, question, is_new=False, id=None):

    print 'set question options: %s' % question

    if not id:
        id = question.id

    print 'set_question_options for id: %s' % id

    is_required = request.POST.get("is_required_%s" % id, None)
    has_score = request.POST.get("has_score_%s" % id, None)
    max_points = request.POST.get("max_points_%s" % id, 1)
    points_prompt = request.POST.get("points_prompt_%s" % id, "")
    has_feedback = request.POST.get("has_feedback_%s" % id, False)
    feedback_prompt = request.POST.get("feedback_prompt_%s" % id, "")
    show_choices = request.POST.get("show_choices_%s" % id, False)
    choices = request.POST.get("choices_%s" % id, "")

    is_hidden_from_applicants = request.POST.get("is_judge_only_%s" % id, False)

    print 'is hidden from applicants? %s' % is_hidden_from_applicants

    question.is_hidden_from_applicants = is_hidden_from_applicants
    if is_hidden_from_applicants:
        question.prompt = ""
        question.is_required = False
        question.raw_choices = ""

    else:        
        if is_required is not None:
            question.is_required = is_required

        if show_choices:
            question.raw_choices = choices
        else:
            question.raw_choices = ""

    if has_score:
        print 'has score: %s' % max_points
        question.max_points = max_points
        question.judge_points_prompt = points_prompt
    else:
        print 'no has score'
        question.max_points = 0
        question.judge_points_prompt = ""

    if has_feedback:
        print 'has feedback'
        question.judge_feedback_prompt = feedback_prompt
    else:
        print 'no feedback'
        question.judge_feedback_prompt = ""

    return question


def should_delete(question):

    #if the applicant can't see it and there's no instructions
    #for the judges, then delete it
    if (not question.prompt) and question.max_score == 0 and (not question.judge_feedback_prompt):

        return True

    else:
        return False


@login_required
def edit_application(request, phase_id):

    phase = get_object_or_404(Phase, id=phase_id)
    competition = phase.competition

    if not has_dash_perms(request, phase.competition.id):
        return HttpResponseRedirect("/no_permissions/")

    if request.method == "POST" and len(request.POST) > 0:

        #existing/edited questions are at old_question_prompt_[pk]
        #existing/edited uploads are at old_upload_prompt_[pk]
        #newly created ones are at question/upload_prompt_[unimportant_number]
        
        for key in request.POST:

            try:
                
                if key.startswith('old_question_prompt_'):

                    id  = key[len('old_question_prompt_'):]
                    prompt = request.POST.get(key)
                    
                    if id != 'new' and id.startswith('new'):

                            q = PitchQuestion(prompt=prompt,
                                              phase=phase)
                            q.save()
                            q = set_question_options(request, q, id=id, is_new=True)
                            q.save()

                            if should_delete(q): 
                                q.delete()
                                        

                    else:

                        #check if existing question has been edited
                        q = PitchQuestion.objects.get(id=id)
                        
                        if q.prompt != prompt:
                            q.prompt = prompt
                            
                        q = set_question_options(request, q)
                        q.save()

                    if should_delete(q):
                        q.delete()
                                    
                elif key.startswith('old_upload_prompt_'):

                    prompt = request.POST.get(key)
                    
                    id  = key[len('old_upload_prompt_'):]

                    if id != 'new' and id.startswith('new'):
                        #create new upload
                        if prompt and len(prompt.strip()) > 0:
                            u = PitchUpload(phase=phase,
                                            prompt=prompt)
                            u.save()

                    else:
                    
                        #check if existing upload has been edited
                        u = PitchUpload.objects.get(id=id)
                        if len(prompt.strip()) == 0:
                            u.delete()
                        elif u.prompt != prompt:
                            u.prompt = prompt
                            u.save()
                        
            except: pass

        setup = phase.setup_steps()
        setup.application_setup = True
        setup.save()

        return HttpResponseRedirect("/dashboard/%s/" % competition.hosted_url)

    
    #this is pretty hacky, but it lets us include the standard
    #question editing chunk to clone for new entries by mimicking
    #the list[i].id format
    new_questions = [ { "id": "new", "max_points": 0 } ]

    return render_to_response('dashboard/edit_application.html', locals())



MONTH_NUMS = { "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
               "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12 }



@login_required
def edit_comp(request, comp_url):

    competition = get_object_or_404(Competition, hosted_url=comp_url)
    alert = ""

    if not has_dash_perms(request, competition.id):
       return HttpResponseRedirect("/no_permissions/")

    if request.method == "POST":

        print 'edit comp, form_type = %s' % request.POST.get("form_type")

        if request.POST.get("form_type") == "competition_info":

            #create model form from POST data
            form = CompetitionInfoForm(request.POST, request.FILES, instance=competition)

            try:
                form.save()
                #success, return to dashboard
                return HttpResponseRedirect("/dashboard/%s/setup/" % competition.hosted_url)

            except:
                #form saving failed, alert user and re-display
                alert = "That URL has already been used by someone. Try something else?"

        elif request.POST.get("form_type") == "phase_info":

            print 'edit comp, form_type=phase_info'

            editing_phase = int(request.GET.get("open", 0))

            print 'editing phase = %s' % editing_phase

            try: 
                phase = Phase.objects.get(id=request.POST.get("phase_id", None))
            except:
                if "new_phase" in request.POST:
                    phase = Phase(competition=competition)
                    print 'new phase'

            if phase:
                form = PhaseForm(request.POST, instance=phase)
                form.save()

                phase.is_deleted = request.POST.get("is_deleted") == "on"
                phase.save()

            if not competition.current_phase:
                competition.current_phase = phase
                competition.save()

            if competition.current_phase.is_deleted:
                competition.current_phase = competition.phases()[0]
                competition.save()

            date = request.POST.get("date", None)
            hour = int(request.POST.get("hour", 23))
            minute = int(request.POST.get("minute", 59))

            if date is not None:

                year = int(date.split()[3])
                month = MONTH_NUMS[date.split()[2].strip(',')]
                day = int(date.split()[1])
                
                phase.deadline = datetime(year, month, day, hour, minute)
                phase.save()
                    
            if editing_phase:
                #if editing a single phase, then we've accomplished the first todo for that phase
                phase.setup_steps().details_confirmed = True
                phase.setup_steps().save()

                #redirect back to that phase page after saving
                return HttpResponseRedirect("/dashboard/%s/manage/" % competition.hosted_url)

            else:
                #if editing the competition's phases all together, then stay on
                #the page for further editing & navigation
                return HttpResponseRedirect("/dashboard/%s/setup/" % competition.hosted_url)

    else: #GET

        editing_phase = int(request.GET.get("open", 0))

        phases = Phase.objects.filter(competition__id=competition.id).filter(is_deleted=False)
        for phase in phases:

            phase.form = PhaseForm(instance=phase)

        new_phase = Phase()
        new_form = PhaseForm(instance=new_phase)

        edit_comp_form = CompetitionInfoForm(instance=competition)

        return render_to_response('dashboard/edit_comp.html', locals())



#organizer has chosen to remove the jduging permissions from
#some number of judges for this phase via the dashboard.
@login_required
def delete_judge_invites(request):

    if not has_dash_perms(request, competition_id):
        return HttpResponseRedirect("/no_permissions/")

    if request.method == "POST" and len(request.POST) > 0:

        if "action" in request.POST:
            action = request.POST["action"]
            if action == "delete_selected":

                for key in request.POST:

                    if key.startswith("is_selected_") and request.POST[key] == "on":

                        id = int(key[len("is_selected_"):])

                        try:
                            invite = JudgeInvitation.objects.get(id=id)
                            if invite.judge.competition.owner == request.user:
                                i.delete()
                        except:
                            pass

    return HttpResponseRedirect('/dashboard/')



#organizer is looking at a list of all the current judges and their performance thus far,
#with options to modify their role
@login_required
def list_judges(request, phase_id):

    phase = get_object_or_404(Phase, id=phase_id)
    competition = phase.competition

    if not has_dash_perms(request, competition.id):
        return HttpResponseRedirect("/no_permissions/")

    #new judges are invited from a small form on the single management/list page,
    #so if it's a post we're going to be inviting a new judge
    if request.method == "POST" and len(request.POST) > 0:

        email = request.POST["invite_list"]

        print 'inviting judge email: %s' % email

        if len(JudgeInvitation.objects.filter(competition__id=competition.id).filter(email=email)) != 0:
            #if we already have a judge for this competition with that email, alert
            #the organizer that nothing needs to happen
            error = "You've already invited that judge."
        else:
            #otherwise, if we haven't already invited this judge, add them
            #to the system and invite them
            invite = JudgeInvitation(competition=competition,
                                     email=email)
            print 'created invitation: %s' % invite
            invite.save()
            print 'saved'
            
            #tell them they're a winner
            judging_link = request.build_absolute_uri("/judge/")
            invite.send_invitation_email(judging_link)

    judge_invitations = JudgeInvitation.objects.filter(competition=competition)
    return render_to_response("dashboard/list_judges.html", locals())
    
    

#view at the scores a judge has previously assigned to a pitch pitch pitch.
#if the person viewing is the same person who made the original judgement,
#they should also be able to edit their answers.
@login_required
def view_judgement(request, judgement_id):

    try:
        judged_pitch = JudgedPitch.objects.get(id=int(judgement_id))
        pitch = judged_pitch.pitch
        can_edit = False

        if judged_pitch.judge.user == request.user:
            #original judge can view & revise
            can_edit = True
        elif pitch.phase.competition.owner == request.user:
            #organizer can view but not edit
            pass
        else:
            #different judges and other randoms can't see it
            return HttpResponseRedirect("/no_permissions/")
    except:
        #unrecognized pitch or judgement
        return HttpResponseRedirect("/no_permissions/")

    questions = pitch.phase.questions()
    uploads = pitch.phase.uploads()

    for question in questions:
        try:
            #question.answer = PitchAnswer.objects.filter(pitch=pitch).get(question=question)
            answers = PitchAnswer.objects.filter(pitch=pitch).filter(question=question)
            question.answer = answers[0]#len(answers) - 1]

        except:
            question.answer = None

        try:
            question.score = JudgedAnswer.objects.filter(judged_pitch=judged_pitch).get(answer=question.answer).score
        except:
            question.score = 0

        try:
            question.feedback = JudgedAnswer.objects.filter(judged_pitch=judged_pitch).get(answer=question.answer).feedback
        except:
            question.feedback = ""

    for upload in uploads:
        try: upload.file = PitchFile.objects.filter(pitch=pitch).get(upload=upload)
        except: upload.file = None

    return render_to_response("dashboard/view_judgement.html", locals())
            
    

@login_required
def view_pitch(request, pitch_id):

    try:
        pitch = Pitch.objects.get(id=pitch_id)
        if pitch.phase.competition.owner != request.user:
            return HttpResponseRedirect("/no_permissions/")
    except:
        return HttpResponseRedirect("/no_permissions/")

    questions = pitch.phase.questions()
    uploads = pitch.phase.uploads()

    for question in questions:
        try: question.answer = PitchAnswer.objects.filter(pitch=pitch).get(question=question)
        except: question.answer = None
            
    for upload in uploads:
        try: upload.file = PitchFile.objects.filter(pitch=pitch).get(upload=upload)
        except: upload.file = None

    return render_to_response("dashboard/view_pitch.html", locals())



#view list of applicants, sort & manipulate them
@login_required
def list_applicants(request, comp_url):

    competition = get_object_or_404(Competition, hosted_url=comp_url)

    if not competition.owner == request.user:
        return HttpResponseRedirect("/no_permissions/")        

    return render_to_response("dashboard/list_applicants.html", locals())


@login_required
def list_judgements(request, phase_id, judge_id):

    judge = get_object_or_404(JudgeInvitation, id=judge_id)
    phase = get_object_or_404(Phase, id=phase_id)
    competition = phase.competition

    #has permissions?
    has_perms = False

    #is an organizer?
    if request.user == competition.owner:
        has_perms = True

    #is the judge in question?
    elif request.user == judge.user:
        has_perms = True

    if not has_perms:
        return HttpResponseRedirect("/no_permissions/")

    judged_pitches = JudgedPitch.objects.filter(pitch__phase__id=phase_id).filter(judge__id=judge_id)

    return render_to_response("dashboard/list_judged_pitches.html", locals())
    


#view list of pitches, sort & manipulate them
@login_required
def list_pitches(request, phase_id, judge_id=None):

    #are comp & phase valid?
    phase = get_object_or_404(Phase, id=phase_id)
    competition = phase.competition

    #is organizer?
    #TODO: this is now totally insecure and doesn't check phase ownership at all
    if competition.owner == request.user:

        phase_1_id = request.GET.get("p1", None)
        phase_2_id = request.GET.get("p2", None)
        
        phase_1 = phase
        phase_2 = None

        if phase_1_id:
            phase_1 = Phase.objects.get(id=int(phase_1_id))

        if phase_2_id:
            phase_2 = Phase.objects.get(id=int(phase_2_id))

        if phase_1 and phase_2: 
            pitches = Pitch.objects.filter( Q( phase=phase_1 ) | Q( phase=phase_2 ) )

        elif phase_1:
            pitches = Pitch.objects.filter( Q( phase=phase_1 ) )

        #make a list of unique teams involved in these pitches
        teams = []
        for pitch in pitches:
            if not pitch.team in teams:
                teams.append(pitch.team)
                pitch.team.pitch_1 = Pitch.objects.get(phase=phase_1, team=pitch.team)
                pitch.team.total_avg = pitch.team.pitch_1.average_score()
                if phase_2_id:
                    try:
                        pitch.team.pitch_2 = Pitch.objects.get(phase=phase_2, team=pitch.team)
                        pitch.team.total_avg += pitch.team.pitch_2.average_score()
                    except:
                        pass

        return render_to_response("dashboard/list_pitches.html", locals())

    else:
        return HttpResponseRedirect("/no_permissions/")
    


#view & manage your competitions
@login_required
def dashboard(request, comp_url=None):

    try:
        request.user.get_profile()
    except:
        #catch old users and give them a profile
        profile = UserProfile(user=request.user)
        profile.save()

    competition = get_object_or_404(Competition, hosted_url=comp_url)
    phase = competition.current_phase
    max_score = phase.max_score()
    score_groups = chart_util.score_distribution(phase.all_judgements(), max(phase.max_score() / 20, 1))

    if competition.owner != request.user:
        return HttpResponseRedirect('/no_permissions/')

    return render_to_response("dashboard/dashboard.html", locals())



#view list of applicants, sort & manipulate them
@login_required
def manage_applicants(request, competition_id):

    competition = Competition.objects.get(pk=competition_id)

    return render_to_response("competition/manage_applicants.html", locals())


from django.shortcuts import render
from django.shortcuts import redirect
from .models import UserDetails, CollectedData
from django.http import HttpResponse
import PyPDF2
import json
import google.generativeai as genai
from django.contrib.auth.decorators import login_required
from django.conf import settings
import os,re,ast
import speech_recognition as sr
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import logging
from django.shortcuts import get_object_or_404
import whisper
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet
model=whisper.load_model("base")
logger = logging.getLogger(__name__)

genai.configure(api_key='*')

# Create your views here.
def login_page(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        try:
            user = UserDetails.objects.get(email=email)
            if user.password == password:
                request.session['logged_in']=True
                request.session['username'] = user.email
                return redirect('home')
            else:
                return render(request, "login.html", {"error": "Password is incorrect."})
        except UserDetails.DoesNotExist:
            return render(request, "login.html", {"error": "User does not exist, please register."})
    return render(request, "login.html")

def register_page(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        print(email, password)
        if UserDetails.objects.filter(email=email).exists():
            return render(request, "signup.html", {"error": "User already exists, please login."})
        else:
            UserDetails.objects.create(email=email, password=password)
            return render(request, "login.html")
    return render(request, "signup.html")

def home_page(request):
    if request.session.get('logged_in'):
        if request.method == "POST":
            content=request.POST.get("content")
            file=request.FILES.get("file")
            # print(content,file)
            if not content and not file:
                return render(request, "home.html", {"username": request.session["username"], "error": "Please enter content or upload a file."})
            extracted_text=""
            if content:
                extracted_text+=content
            if file:
                if file.name.endswith(".pdf"):
                    extracted_text+=extractor(file)
                else:
                    return render(request, "home.html", {"username": request.session["username"], "error": "Please upload a PDF file."})
            question_answer=get_questions_and_answers_from_openai(extracted_text)
            question_answer=question_answer[8:-5]
            question_answer=json.loads(question_answer)
            CollectedData.objects.all().delete()
            database(question_answer)
            return redirect('starttestpage')

        return render(request, "home.html", {"username": request.session["username"]})
    else:
        return render(request, "login.html")   
    
        
def extractor(file):
    reader = PyPDF2.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text
       
def get_questions_and_answers_from_openai(content):
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(f"generate all possible question with answer in a dictionary  for {content} with question as key and answer as value without any backtick and without any other text, only json format")
    return response.text

def database(question_answer):
    for question, answer in question_answer.items():
        CollectedData.objects.create(question=question, answer=answer)

def starttestpage(request):
    return render(request, "starttestpage.html")  
        

def logout(request):
    if request.session.get('logged_in'):
        request.session.flush()
        return redirect('login')
    else:
        return redirect('login')
   
def showquestions(request):
    if not request.session.get('logged_in'):
        return redirect('login')
    return redirect('questions',question_number=1)

def questions(request, question_number):
    if not request.session.get('logged_in'):
        return redirect('login')
    if question_number>CollectedData.objects.count():
        return redirect('scorepage')
    question = CollectedData.objects.get(question_id=question_number)
    return render(request, 'question.html', {'question': question, 'question_number': question_number})
def scorepage(request):
    if not request.session.get('logged_in'):
        return redirect('login')
    return render( request,'scorepage.html')



    
@csrf_exempt
def convert_audio(request):
    if request.method == 'POST' and request.FILES.get('audio'):
        audio_file = request.FILES['audio']
        question_number = request.POST.get('question_number')  # Get question number from the form data

        if not question_number:
            return JsonResponse({'error': 'Question number is missing.'}, status=400)

        # Save the uploaded file
        file_path = os.path.join('media', 'uploaded_audio.webm')  # Save file temporarily
        with open(file_path, 'wb') as f:
            for chunk in audio_file.chunks():
                f.write(chunk)

        try:
            # Transcribe the audio using Whisper (assuming `model.transcribe()` is defined)
            result = model.transcribe(file_path)

            # Extract text from the result
            transcribed_text = result['text']
            print(transcribed_text)

            # Get the question by ID
            question = CollectedData.objects.get(question_id=question_number)

            # Save the transcribed text into the model's useranswer field
            question.useranswer = transcribed_text
            question.save()

            return JsonResponse({'success': True, 'transcribed_text': transcribed_text})

        except Exception as e:
            return JsonResponse({'error': f'Error during transcription: {str(e)}'}, status=500)
    else:
        return JsonResponse({'error': 'No audio file provided.'}, status=400)
    
    
def get_next_question(request):
     question_number = request.GET.get('question_number')
     return redirect('questions', question_number=question_number)
 
 
 


def generate_pdf(results_with_status):
    # Create a BytesIO buffer to store the PDF content in memory
    buffer = BytesIO()

    # Create a canvas to generate the PDF
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Define margins
    left_margin = 50
    right_margin = 50
    y_position = height - 50  # Start below the top margin

    # Title of the report
    p.setFont("Helvetica-Bold", 16)
    p.drawString(left_margin, y_position, "Analysis Report")
    y_position -= 30  # Add vertical space

    # Set font for the content
    p.setFont("Helvetica", 12)

    # Add details for each question
    for result in results_with_status:
        # Prepare text with proper wrapping
        def draw_wrapped_text(canvas, x, y, text, max_width):
            from reportlab.lib.utils import simpleSplit
            lines = simpleSplit(text, "Helvetica", 12, max_width)
            for line in lines:
                canvas.drawString(x, y, line)
                y -= 15
            return y

        # Question and Answer Details
        question_text = f"Q{result['question_id']}: {result['question']}"
        actual_answer_text = f"Actual Answer: {result['answer']}"
        user_answer_text = f"Your Answer: {result['useranswer']}"
        status_text = f"Status: {result['status']}"
        correct_text = f"Correct? {'Yes' if result['correct'] else 'No'}"

        # Draw text with wrapping
        y_position = draw_wrapped_text(p, left_margin, y_position, question_text, width - right_margin - left_margin)
        y_position -= 10
        y_position = draw_wrapped_text(p, left_margin, y_position, actual_answer_text, width - right_margin - left_margin)
        y_position -= 10
        y_position = draw_wrapped_text(p, left_margin, y_position, user_answer_text, width - right_margin - left_margin)
        y_position -= 10
        y_position = draw_wrapped_text(p, left_margin, y_position, status_text, width - right_margin - left_margin)
        y_position -= 10
        y_position = draw_wrapped_text(p, left_margin, y_position, correct_text, width - right_margin - left_margin)
        y_position -= 20  # Add spacing before the next question

        # Highlight incorrect answers
        if not result['correct']:
            p.setFillColorRGB(1, 0, 0)  # Set red color for incorrect answers
            p.drawString(left_margin, y_position + 10, "Note: Your answer is incorrect.")
            p.setFillColorRGB(0, 0, 0)  # Reset color
            y_position -= 20

        # Add a page break if the content goes below the bottom margin
        if y_position < 50:
            p.showPage()
            p.setFont("Helvetica", 12)
            y_position = height - 50

    # Finalize the PDF and return it as a response
    p.save()

    # Seek to the start of the BytesIO buffer
    buffer.seek(0)
    
    # Return the PDF as an HTTP response
    return buffer



def analysis(request):
    try:
        # Collect all questions and answers
        result = []
        for i in range(1, CollectedData.objects.count() + 1):
            question = CollectedData.objects.filter(question_id=i).first()
            if question:  # Ensure question existsquestion_set.append({'question_id': question.question_id, 'question':question.question})
                result.append({'answer': question.answer, 'useranswer': question.useranswer})
        
        # Generate AI response
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            f"Evaluate the similarity between the provided actual and user answers, focusing on both meaning and accuracy for {result} and return only a single list of 'yes' and 'no' for each response in return"
)
        print(response.text)
        ans=response.text
        print("------->",type(ans))

        # Clean up response text and generate list
        # response_text =''.join(response.text.strip().split(','))  # Remove trailing spaces or newlines
        response_text= ast.literal_eval(response.text)
        print(type(response_text),response_text)
        response_list = response_text
        # print(response_list)  # Check the response list for debugging

        # Initialize counters for correct and wrong answers
        total = len(response_list)
        correct = 0
        wrong = 0
        results_with_status = []  # This will store each question with status (yes/no)

        for i in range(1, total + 1):
            question = CollectedData.objects.filter(question_id=i).first()
            

        # Clean up the AI response and compare in lowercase
            ai_response = response_list[i - 1].strip().lower()  # Strip spaces and convert to lowercase
            print(ai_response)

            if ai_response == "yes":
                correct += 1
            elif ai_response == "no":
                wrong += 1
            # print(correct, wrong)

        # Add the result with status (yes/no) to the list
            results_with_status.append({
                'question_id': question.question_id,
                'question': question.question,
                'answer': question.answer,
                'useranswer': question.useranswer,
                'status': ai_response,  # "yes" or "no"
                'correct': ai_response == "yes"
                })

        

          

        # Handle PDF generation and download
        if 'download_report' in request.GET:
            pdf = generate_pdf(results_with_status)
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="analysis_report.pdf"'
            return response

        # Pass data to the template
        return render(request, 'analysis.html', {
            'total': total,
            'correct': correct,
            'wrong': wrong,
            'results_with_status': results_with_status  # Send detailed results for each question
        })

    except Exception as e:
        print(f"Error in analysis: {e}")
        return HttpResponse("An error occurred during analysis.")

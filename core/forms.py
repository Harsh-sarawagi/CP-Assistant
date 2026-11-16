# filepath: core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser, PersonalNote

class CustomRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        # The fields we want the user to fill out when signing up
        fields = ('username', 'email', 'codeforces_handle')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Automatically apply Bootstrap styling to all fields
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ('email', 'codeforces_handle')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

            # filepath: core/forms.py

class CodeReviewForm(forms.Form):
    language = forms.ChoiceField(
        required=False,
        choices=[('', 'Auto-detect'), ('C++', 'C++'), ('Python', 'Python'), ('Java', 'Java'), ('Other', 'Other')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    problem_link = forms.URLField(
        label="Problem URL",
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'e.g., https://codeforces.com/problemset/problem/1/A'})
    )
    code = forms.CharField(
        label="Your Source Code",
        max_length=40000,
        strip=False,
        widget=forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 12, 'placeholder': 'Paste your C++ or Python code here...'})
    )

    def clean_problem_link(self):
        from .services.urls import problem_url
        result = problem_url(self.cleaned_data['problem_link'])
        if not result:
            raise forms.ValidationError('Use a Codeforces problemset, contest, or gym problem URL.')
        return result

    def clean_code(self):
        code = self.cleaned_data['code']
        if not code.strip():
            raise forms.ValidationError('Paste your source code before requesting a review.')
        return code


class PersonalNoteForm(forms.ModelForm):
    class Meta:
        model = PersonalNote
        fields = ('title', 'content', 'topic')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['content'].widget.attrs['rows'] = 6

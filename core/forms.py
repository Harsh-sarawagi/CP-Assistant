# filepath: core/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser

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
    problem_link = forms.URLField(
        label="Problem URL",
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'e.g., https://codeforces.com/problemset/problem/1/A'})
    )
    code = forms.CharField(
        label="Your Source Code",
        widget=forms.Textarea(attrs={'class': 'form-control font-monospace', 'rows': 12, 'placeholder': 'Paste your C++ or Python code here...'})
    )

class ComparisonForm(forms.Form):
    handle_1 = forms.CharField(
        label="Player 1 (Your Handle)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CF username'})
    )
    handle_2 = forms.CharField(
        label="Player 2 (Rival Handle)",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'CF username'})
    )
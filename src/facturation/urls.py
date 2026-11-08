from django.urls import path

from facturation import views

app_name = "facturation"

urlpatterns = [
    path("factures/<int:pk>/pdf/", views.facture_pdf, name="pdf"),
]

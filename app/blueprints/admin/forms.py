"""Formularios WTForms del panel de administración."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    BooleanField, FloatField, IntegerField, PasswordField,
    StringField, TextAreaField,
)
from wtforms.validators import (
    DataRequired, Length, NumberRange, Optional, ValidationError,
)

from app.models import AdminUser


class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Contraseña", validators=[DataRequired()])


class FranquiciadoForm(FlaskForm):
    nombre            = StringField("Nombre",        validators=[DataRequired(), Length(max=120)])
    jt_user           = StringField("Usuario JMS",   validators=[DataRequired(), Length(max=120)])
    jt_pass           = PasswordField("Contraseña JMS", validators=[Length(max=255)])
    wa_grupo_id       = StringField("ID Grupo WhatsApp (alertas)",  validators=[DataRequired(), Length(max=120)])
    wa_status_grupo_id = StringField("ID Grupo WhatsApp (monitoreo)",validators=[Optional(), Length(max=120)])
    textmebot_api_key = StringField("API Key textmebot", validators=[DataRequired(), Length(max=120)])
    activo            = BooleanField("Activo", default=True)
    notas             = TextAreaField("Notas",        validators=[Optional(), Length(max=2000)])
    # Reglas de entrega personalizadas
    horas_total_entrega   = IntegerField("Plazo total de entrega (horas)",  validators=[DataRequired(), NumberRange(min=24, max=720)])
    horas_primera_gestion = IntegerField("Primera gestión máx (horas)",     validators=[DataRequired(), NumberRange(min=4, max=240)])
    horas_entre_gestiones = IntegerField("Máx horas entre gestiones",       validators=[DataRequired(), NumberRange(min=4, max=240)])

    def validate_jt_pass(self, field):
        """Contraseña solo requerida al crear; al editar se puede dejar vacía."""
        # La ruta distingue crear/editar; aquí solo validamos longitud mínima si se llenó.
        if field.data and len(field.data) < 4:
            raise ValidationError("La contraseña debe tener al menos 4 caracteres.")


class ImportarWaybillsForm(FlaskForm):
    waybills = TextAreaField(
        "Códigos de guía (uno por línea)",
        validators=[DataRequired(), Length(max=50000)],
        description="Ingresa los códigos JyT separados por saltos de línea.",
    )


class ImportarExcelForm(FlaskForm):
    """Formulario para subir un Excel exportado desde el portal J&T JMS."""
    excel_file = FileField(
        "Archivo Excel (.xlsx)",
        validators=[
            FileRequired(message="Selecciona un archivo Excel."),
            FileAllowed(["xlsx", "xls"], "Solo se permiten archivos Excel (.xlsx / .xls)."),
        ],
    )


class ConfiguracionForm(FlaskForm):
    umbral_dia            = FloatField("Umbral 8am–9pm (horas)",          validators=[DataRequired(), NumberRange(min=0.5, max=48)])
    umbral_22             = FloatField("Umbral 10pm (horas)",               validators=[DataRequired(), NumberRange(min=0.5, max=48)])
    umbral_23             = FloatField("Umbral 11pm (horas)",               validators=[DataRequired(), NumberRange(min=0.5, max=48)])
    hora_inicio           = IntegerField("Hora inicio (Perú)",             validators=[DataRequired(), NumberRange(min=0, max=23)])
    hora_fin              = IntegerField("Hora fin (Perú)",                validators=[DataRequired(), NumberRange(min=0, max=23)])
    delay_whatsapp        = FloatField("Delay entre envíos WA (seg)",       validators=[DataRequired(), NumberRange(min=0, max=60)])
    sync_dias_atras       = IntegerField("Días atrás para sincronizar",     validators=[DataRequired(), NumberRange(min=1, max=365)])
    sync_time_type        = IntegerField("Tipo de fecha (timeType)",        validators=[DataRequired(), NumberRange(min=0, max=1)])


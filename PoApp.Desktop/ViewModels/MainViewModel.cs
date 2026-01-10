using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using PoApp.Core.Models;
using PoApp.Desktop.Models;
using PoApp.Desktop.Services;

namespace PoApp.Desktop.ViewModels;

public partial class MainViewModel : ObservableObject
{
    public ObservableCollection<MaterialSpecRecord> Specs { get; } = new();
    public ObservableCollection<string> SpecTypes { get; } = new() { "", "SA", "A" };
    public ObservableCollection<string> AvailableGrades { get; } = new();
    public ObservableCollection<OrderingOption> OrderingOptions { get; } = new();
    public ObservableCollection<RequiredFieldInput> RequiredFields { get; } = new();

    [ObservableProperty] private string? selectedSpecType;
    [ObservableProperty] private MaterialSpecRecord? selectedSpec;
    [ObservableProperty] private string? selectedGrade;
    [ObservableProperty] private string astmDisplay = "";
    [ObservableProperty] private string generatedText = "";

    private readonly Dictionary<string, List<string>> requiredFieldMap;
    private readonly Dictionary<string, List<string>> endFinishRules;

    public MainViewModel()
    {
        var dataset = JsonMaterialRepository.LoadFromRepoDataFolder();
        requiredFieldMap = LoadMap("ordering-required-fields.json");
        endFinishRules = LoadMap("end-finish-normalized.json");

        foreach (var m in dataset.Materials.OrderBy(m => m.SpecDesignation))
            Specs.Add(m);

        if (Specs.Count > 0)
            SelectedSpec = Specs[0];
    }

    partial void OnSelectedSpecChanged(MaterialSpecRecord? value)
    {
        AvailableGrades.Clear();
        OrderingOptions.Clear();
        RequiredFields.Clear();

        if (value is null)
        {
            AstmDisplay = "";
            SelectedGrade = null;
            GeneratedText = "";
            return;
        }

        AstmDisplay = string.IsNullOrWhiteSpace(value.AstmSpec) && string.IsNullOrWhiteSpace(value.AstmYear)
            ? ""
            : $"{value.AstmSpec}-{value.AstmYear}".Trim('-');

        foreach (var g in value.Grades ?? [])
            AvailableGrades.Add(g);

 


        SelectedGrade = AvailableGrades.FirstOrDefault();

        foreach (var item in value.OrderingInfoItems ?? [])
            OrderingOptions.Add(new OrderingOption(item, isSelected: true));

        BuildRequiredFields(value);

        Regenerate();
    }

    partial void OnSelectedGradeChanged(string? value)
    {
        var gradeField = RequiredFields.FirstOrDefault(field =>
            string.Equals(field.Label, "Grade / Class / Type", StringComparison.OrdinalIgnoreCase));
        if (gradeField is not null && gradeField.Value != value)
            gradeField.Value = value;

        Regenerate();
    }

    partial void OnSelectedSpecTypeChanged(string? value)
    {
        Regenerate();
    }

    [RelayCommand]
private void ToggleAllOrdering(object? parameter)
{
    // WPF often passes CommandParameter as string ("True"/"False")
    bool selectAll =
        parameter is bool b ? b :
        bool.TryParse(parameter?.ToString(), out var parsed) && parsed;

    foreach (var opt in OrderingOptions)
        opt.IsSelected = selectAll;

    Regenerate();
}
[RelayCommand]
    private void SelectAllOrdering()
    {
        foreach (var opt in OrderingOptions)
            opt.IsSelected = true;

        Regenerate();
    }

    [RelayCommand]
    private void SelectNoneOrdering()
    {
        foreach (var opt in OrderingOptions)
            opt.IsSelected = false;

        Regenerate();
    }
[RelayCommand]
    private void CopyToClipboard()
    {
        if (!string.IsNullOrWhiteSpace(GeneratedText))
            Clipboard.SetText(GeneratedText);
    }













    [RelayCommand]
    private void Regenerate()
    {
        if (SelectedSpec is null)
        {
            GeneratedText = "";
            return;
        }

 









        var selectedNotes = OrderingOptions.Where(o => o.IsSelected).Select(o => o.Text);
        var requiredEntries = RequiredFields.Select(field => new RequiredFieldEntry(
            field.Label,
            field.Value,
            field.Note,
            field.Options));

        GeneratedText = PoTextGenerator.Generate(SelectedSpec, SelectedGrade, selectedNotes, requiredEntries, SelectedSpecType);
    }

    private void BuildRequiredFields(MaterialSpecRecord spec)
    {
        RequiredFields.Clear();

        if (!requiredFieldMap.TryGetValue(spec.SpecDesignation, out var required))
            return;

        if (required.Contains("Quantity"))
            AddRequiredField(new RequiredFieldInput("Quantity"));

        if (required.Contains("Grade / Class / Type"))
            AddRequiredField(BuildGradeField());

        if (required.Contains("Length (specific or random)"))
            AddRequiredField(new RequiredFieldInput("Length (specific or random)"));

        if (required.Contains("Size / OD / Thickness"))
            AddRequiredField(new RequiredFieldInput("Size / OD / Thickness"));

        if (required.Contains("End Finish"))
            AddRequiredField(BuildEndFinishField(spec.SpecDesignation));

        if (required.Contains("Manufacture (seamless/welded)"))
            AddRequiredField(BuildManufactureField());

        if (required.Contains("Test Report"))
            AddRequiredField(new RequiredFieldInput("Test Report"));
    }

    private RequiredFieldInput BuildGradeField()
    {
        var field = new RequiredFieldInput("Grade / Class / Type");
        var options = AvailableGrades
            .Where(grade => !string.IsNullOrWhiteSpace(grade))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (options.Count > 0)
        {
            options.Insert(0, "");
            field.Options = new ObservableCollection<string>(options);
        }

        field.Value = SelectedGrade;
        return field;
    }

    private static RequiredFieldInput BuildManufactureField()
    {
        var options = new[]
        {
            "",
            "Seamless",
            "Welded",
            "Electric-resistance welded",
            "Electric-fusion welded",
            "Hot-finished",
            "Cold-drawn"
        };

        return new RequiredFieldInput("Manufacture (seamless/welded)")
        {
            Options = new ObservableCollection<string>(options)
        };
    }

    private RequiredFieldInput BuildEndFinishField(string spec)
    {
        var field = new RequiredFieldInput("End Finish");

        if (!endFinishRules.TryGetValue(spec, out var rules))
            return field;

        var options = new List<string>();
        var notes = new List<string>();

        foreach (var rule in rules)
        {
            if (rule.StartsWith("Options:", StringComparison.OrdinalIgnoreCase))
            {
                var parts = rule["Options:".Length..]
                    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                options.AddRange(parts);
                continue;
            }

            if (rule.StartsWith("A999/A999M", StringComparison.OrdinalIgnoreCase))
            {
                notes.Add("Plain ends unless specified.");
                continue;
            }

            notes.Add(rule);
        }

        if (options.Count > 0)
        {
            options = options.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            options.Insert(0, "");
            field.Options = new ObservableCollection<string>(options);
        }

        if (notes.Count > 0)
            field.Note = string.Join(" ", notes);

        return field;
    }

    private void AddRequiredField(RequiredFieldInput field)
    {
        field.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(RequiredFieldInput.Value))
            {
                if (string.Equals(field.Label, "Grade / Class / Type", StringComparison.OrdinalIgnoreCase)
                    && SelectedGrade != field.Value)
                    SelectedGrade = field.Value;

                Regenerate();
            }
        };

        RequiredFields.Add(field);
    }

    private static Dictionary<string, List<string>> LoadMap(string fileName)
    {
        var path = DataFileLocator.FindDataFile(fileName);
        if (string.IsNullOrWhiteSpace(path))
            return new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);

        var json = File.ReadAllText(path);
        var data = JsonSerializer.Deserialize<Dictionary<string, List<string>>>(json);

        return data ?? new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
    }
}

public sealed partial class OrderingOption : ObservableObject
{
 






   public OrderingOption(string text, bool isSelected)
    {
        Text = text;
        IsSelected = isSelected;
    }

    public string Text { get; }







    [ObservableProperty]
    private bool isSelected;
}

public sealed partial class RequiredFieldInput : ObservableObject
{
    public RequiredFieldInput(string label)
    {
        Label = label;
        options = new ObservableCollection<string>();
    }

    public string Label { get; }

    [ObservableProperty]
    private string? value;

    [ObservableProperty]
    private string? note;

    private ObservableCollection<string> options;

    public ObservableCollection<string> Options
    {
        get => options;
        set
        {
            options = value;
            OnPropertyChanged(nameof(Options));
            OnPropertyChanged(nameof(HasOptions));
        }
    }

    public bool HasOptions => Options.Count > 0;
}

